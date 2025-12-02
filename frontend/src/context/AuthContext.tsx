import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import type { HITLMode, UserSettings } from '../services/api';
import { apiService } from '../services/api';

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
}

const AuthContext = createContext<AuthContextType | null>(null);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(localStorage.getItem('token'));
  const [hitlMode, setHitlMode] = useState<HITLMode>('review');

  useEffect(() => {
    if (token) {
      // Verify token and get user info
      apiService.getMe(token)
        .then(userData => {
          setUser(userData);
          // Set HITL mode from user settings
          if (userData.settings?.hitl_mode) {
            setHitlMode(userData.settings.hitl_mode);
          }
        })
        .catch(() => logout());
    }
  }, [token]);

  const login = (newToken: string) => {
    localStorage.setItem('token', newToken);
    setToken(newToken);
  };

  const logout = () => {
    localStorage.removeItem('token');
    setToken(null);
    setUser(null);
    setHitlMode('review');
  };

  const toggleHitlMode = useCallback(async () => {
    if (!token) return;
    
    const newMode: HITLMode = hitlMode === 'review' ? 'auto' : 'review';
    
    try {
      // Update on server
      const updatedSettings = await apiService.updateUserSettings(token, { hitl_mode: newMode });
      setHitlMode(updatedSettings.hitl_mode);
      
      // Update local user state
      if (user) {
        setUser({ ...user, settings: updatedSettings });
      }
    } catch (error) {
      console.error('Failed to update HITL mode:', error);
    }
  }, [token, hitlMode, user]);

  return (
    <AuthContext.Provider value={{ 
      user, 
      token, 
      login, 
      logout, 
      isAuthenticated: !!token,
      hitlMode,
      toggleHitlMode
    }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
