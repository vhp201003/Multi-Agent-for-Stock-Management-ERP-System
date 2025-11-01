import { useState } from 'react'
import Sidebar from './components/Sidebar'
import ChatInterface from './components/ChatInterface'
import './App.css'

function App() {
  const [currentConversationId, setCurrentConversationId] = useState<string>('')

  const handleSelectConversation = (conversationId: string) => {
    setCurrentConversationId(conversationId)
  }

  const handleNewConversation = () => {
    setCurrentConversationId('')
  }

  return (
    <div className="app">
      <Sidebar 
        onSelectConversation={handleSelectConversation}
        onNewConversation={handleNewConversation}
        currentConversationId={currentConversationId}
      />
      <ChatInterface conversationId={currentConversationId} />
    </div>
  )
}

export default App
