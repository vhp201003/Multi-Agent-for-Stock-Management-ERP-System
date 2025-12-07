import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
} from "react";
import type { HITLMode, ThemeMode, UserSettings } from "../services/api";
import { apiService } from "../services/api";

interface User {
  id: string;
  email: string;
  full_name?: string;
  settings?: UserSettings;
}

interface AuthContextType {
  user: User | null;
  token: string | null;
  login: (token: string) => void;
  logout: () => void;
  isAuthenticated: boolean;
  hitlMode: HITLMode;
  toggleHitlMode: () => Promise<void>;
  theme: ThemeMode;
  toggleTheme: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | null>(null);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const [user, setUser] = useState<User | null>(null);
  // Try both 'authToken' (new) and 'token' (legacy)
  const [token, setToken] = useState<string | null>(
    localStorage.getItem("authToken") || localStorage.getItem("token")
  );
  const [hitlMode, setHitlMode] = useState<HITLMode>("review");
  const [theme, setTheme] = useState<ThemeMode>("dark");

  // Apply theme to document
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  useEffect(() => {
    if (token) {
      // Verify token and get user info
      apiService
        .getMe(token)
        .then((userData) => {
          setUser(userData);
          // Set HITL mode from user settings
          if (userData.settings?.hitl_mode) {
            setHitlMode(userData.settings.hitl_mode);
          }
          // Set theme from user settings
          if (userData.settings?.theme) {
            setTheme(userData.settings.theme);
          }
        })
        .catch(() => logout());
    }
  }, [token]);

  const login = (newToken: string) => {
    // Store in both keys for backward compatibility
    localStorage.setItem("authToken", newToken);
    localStorage.setItem("token", newToken);
    setToken(newToken);
    console.log("[Auth] Login successful, token stored");
  };

  const logout = () => {
    // Remove both keys
    localStorage.removeItem("authToken");
    localStorage.removeItem("token");
    setToken(null);
    setUser(null);
    setHitlMode("review");
    setTheme("dark");
    console.log("[Auth] Logout successful, token removed");
  };

  const toggleHitlMode = useCallback(async () => {
    if (!token) return;

    const newMode: HITLMode = hitlMode === "review" ? "auto" : "review";

    try {
      // Update on server
      const updatedSettings = await apiService.updateUserSettings(token, {
        hitl_mode: newMode,
      });
      setHitlMode(updatedSettings.hitl_mode);

      // Update local user state
      if (user) {
        setUser({ ...user, settings: updatedSettings });
      }
    } catch (error) {
      console.error("Failed to update HITL mode:", error);
    }
  }, [token, hitlMode, user]);

  const toggleTheme = useCallback(async () => {
    const newTheme: ThemeMode = theme === "dark" ? "light" : "dark";

    // Apply immediately for instant feedback
    setTheme(newTheme);

    if (!token) return;

    try {
      // Sync with server
      const updatedSettings = await apiService.updateUserSettings(token, {
        theme: newTheme,
      });

      // Update local user state
      if (user) {
        setUser({ ...user, settings: updatedSettings });
      }
    } catch (error) {
      console.error("Failed to update theme:", error);
      // Revert on error
      setTheme(theme);
    }
  }, [token, theme, user]);

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        login,
        logout,
        isAuthenticated: !!token,
        hitlMode,
        toggleHitlMode,
        theme,
        toggleTheme,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
};
