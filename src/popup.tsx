import { useState, useEffect, useRef } from "react"
import "./index.css"
import logo from "./assets/icon.png"

type Screen = "welcome" | "options" | "chat"
type Context = "testcase" | "refactoring" | null

interface Message {
  id: string
  role: "user" | "assistant"
  content: string
  timestamp: number
}

interface ChatHistory {
  testcase: Message[]
  refactoring: Message[]
}

function IndexPopup() {
  const [screen, setScreen] = useState<Screen>("welcome")
  const [context, setContext] = useState<Context>(null)
  const [chatHistory, setChatHistory] = useState<ChatHistory>({
    testcase: [],
    refactoring: []
  })
  const [inputValue, setInputValue] = useState("")
  const [selectedCode, setSelectedCode] = useState<string>("")
  const [isProcessing, setIsProcessing] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom when new messages arrive
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }

  useEffect(() => {
    scrollToBottom()
  }, [chatHistory, isProcessing])

  // Load chat history from storage on mount
  useEffect(() => {
    // In a real implementation, you might want to persist this
    // For now, it's just in memory
    const savedHistory = {
      testcase: [],
      refactoring: []
    }
    setChatHistory(savedHistory)
  }, [])

  // Listen for selected code from content script
  useEffect(() => {
    const messageListener = (message: any) => {
      if (message.type === "CODE_SELECTED") {
        setSelectedCode(message.code)
      }
    }

    chrome.runtime.onMessage.addListener(messageListener)
    return () => chrome.runtime.onMessage.removeListener(messageListener)
  }, [])

  const handleWelcomeClick = () => {
    setScreen("options")
  }

  const handleContextSelect = (selectedContext: Context) => {
    setContext(selectedContext)
    setScreen("chat")
  }

  const handleSendMessage = async () => {
    if (!inputValue.trim() && !selectedCode.trim()) return
    if (!context) return

    const messageContent = selectedCode 
      ? `${inputValue}\n\n\`\`\`\n${selectedCode}\n\`\`\``
      : inputValue

    const userMessage: Message = {
      id: Date.now().toString(),
      role: "user",
      content: messageContent,
      timestamp: Date.now()
    }

    // Add user message to chat history
    setChatHistory(prev => ({
      ...prev,
      [context]: [...prev[context], userMessage]
    }))

    setInputValue("")
    setSelectedCode("")
    setIsProcessing(true)

    // Simulate AI response (replace with actual API call)
    // You can integrate with your backend API here
    setTimeout(() => {
      const assistantMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: "assistant",
        content: context === "testcase" 
          ? `Here are the generated test cases for your code:

\`\`\`javascript
describe('Test Suite', () => {
  it('should handle valid input', () => {
    const result = yourFunction(validInput);
    expect(result).toBeDefined();
  });

  it('should handle edge cases', () => {
    const result = yourFunction(edgeCase);
    expect(result).toEqual(expectedValue);
  });

  it('should throw error for invalid input', () => {
    expect(() => yourFunction(invalidInput)).toThrow();
  });
});
\`\`\`

These test cases cover the main functionality, edge cases, and error handling.`
          : `Here's the refactored version of your code:

\`\`\`javascript
// Refactored with improvements:
// - Better naming conventions
// - Removed code duplication
// - Improved error handling
// - Added comments for clarity

const optimizedFunction = (input) => {
  // Validate input
  if (!input) {
    throw new Error('Input is required');
  }

  // Process data efficiently
  const result = processData(input);
  
  return result;
};

// Helper function for better modularity
const processData = (data) => {
  // Implementation here
  return data.map(item => transform(item));
};
\`\`\`

**Improvements made:**
- Separated concerns with helper functions
- Added input validation
- Improved readability with better naming
- Added error handling`,
        timestamp: Date.now()
      }

      setChatHistory(prev => ({
        ...prev,
        [context]: [...prev[context], assistantMessage]
      }))
      setIsProcessing(false)
    }, 1500)
  }

  const handleContextSwitch = () => {
    setScreen("options")
  }

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSendMessage()
    }
  }

  const currentMessages = context ? chatHistory[context] : []

  return (
    <div className="popup-container">
      {screen === "welcome" && (
        <div className="popup-card welcome-screen">
          <div className="popup-icon-large option-icon">
            <img src={logo} alt="App Icon" width={64} height={64} />
          </div>
          
          <h1 className="welcome-title">Codexter</h1>
          
          <p className="welcome-subtitle">
            Your AI-powered code testing and refactoring tool.
          </p>
          <button className="primary-button" onClick={handleWelcomeClick}>
            Get Started →
          </button>
          <h5 className="welcome-subtitle">v{chrome.runtime.getManifest().version}</h5>
        </div>
      )}

      {screen === "options" && (
        <div className="popup-card options-screen">
          <div className="popup-icon">
            <img src={logo} alt="App Icon" width={24} height={24} />
            <span>Codexter</span>
          </div>
          <h2 className="options-title">Choose Your Task</h2>
          <p className="options-subtitle">What would you like to do today?</p>
          <div className="options-list">
            <button
              className="option-card"
              onClick={() => handleContextSelect("testcase")}
            >
              <div className="option-icon">🧪</div>
              <div className="option-content">
                <h3>Test Case Generation</h3>
                <p>Generate comprehensive test cases for your code</p>
              </div>
              <div className="option-arrow">→</div>
            </button>
            <button
              className="option-card"
              onClick={() => handleContextSelect("refactoring")}
            >
              <div className="option-icon">🔧</div>
              <div className="option-content">
                <h3>Code Refactoring</h3>
                <p>Improve and optimize your code structure</p>
              </div>
              <div className="option-arrow">→</div>
            </button>
          </div>
        </div>
      )}

      {screen === "chat" && context && (
        <div className="popup-card chat-screen">
          <div className="chat-header">
            <div className="chat-header-left">
              <img src={logo} alt="App Icon" width={20} height={20} />
              <span className="chat-context">
                {context === "testcase" ? "Test Generation" : "Code Refactoring"}
              </span>
            </div>
            <button className="switch-button" onClick={handleContextSwitch}>
              ⚙ Switch
            </button>
          </div>

          <div className="chat-messages">
            {currentMessages.length === 0 ? (
              <div className="empty-state">
                <div className="empty-icon">
                  {context === "testcase" ? "🧪" : "🔧"}
                </div>
                <h3>
                  {context === "testcase"
                    ? "Generate Test Cases"
                    : "Refactor Your Code"}
                </h3>
                <p>
                  {context === "testcase"
                    ? "Send your code to generate comprehensive test cases"
                    : "Send your code to get refactoring suggestions"}
                </p>
                <div className="tip">💡 Tip: Select code on any webpage to auto-paste it here</div>
              </div>
            ) : (
              <>
                {currentMessages.map((message) => (
                  <div
                    key={message.id}
                    className={`message ${message.role === "user" ? "user-message" : "assistant-message"}`}
                  >
                    <div className="message-avatar">
                      {message.role === "user" ? "👤" : "🤖"}
                    </div>
                    <div className="message-content">{message.content}</div>
                  </div>
                ))}
                {isProcessing && (
                  <div className="message assistant-message">
                    <div className="message-avatar">🤖</div>
                    <div className="message-content typing-indicator">
                      <span></span>
                      <span></span>
                      <span></span>
                    </div>
                  </div>
                )}
                <div ref={messagesEndRef} />
              </>
            )}
          </div>

          <div className="chat-input-container">
            {selectedCode && (
              <div className="selected-code-badge">
                <span>📋 Code snippet attached ({selectedCode.length} chars)</span>
                <button onClick={() => setSelectedCode("")}>✕</button>
              </div>
            )}
            <div className="chat-input-wrapper">
              <textarea
                className="chat-input"
                placeholder={
                  selectedCode
                    ? "Add instructions for the selected code..."
                    : "Paste your code or select code from any webpage..."
                }
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={handleKeyPress}
                rows={2}
              />
              <button
                className="send-button"
                onClick={handleSendMessage}
                disabled={!inputValue.trim() && !selectedCode.trim()}
              >
                <span className="send-icon">➤</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default IndexPopup