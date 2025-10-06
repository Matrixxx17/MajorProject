/**
 * Background Service Worker for Codexter Extension
 * Handles communication between content script and popup
 */

console.log('Codexter background service worker started');

// Store selected code temporarily
let selectedCodeStore: string = '';
let lastSelectionTime: number = 0;

/**
 * Listen for messages from content script and popup
 */
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  console.log('Background received message:', message.type);
  
  // Handle code selection from content script
  if (message.type === 'CODE_SELECTED') {
    selectedCodeStore = message.code;
    lastSelectionTime = message.timestamp || Date.now();
    
    console.log('Code stored in background:', message.code.length, 'characters');
    
    // Try to forward to popup if it's open
    chrome.runtime.sendMessage(message).catch((error) => {
      // Popup might not be open, that's okay
      console.log('Popup not open, code stored for later');
    });
    
    sendResponse({ success: true });
    return true;
  }
  
  // Handle request for stored code from popup
  if (message.type === 'GET_STORED_CODE') {
    sendResponse({ 
      code: selectedCodeStore,
      timestamp: lastSelectionTime
    });
    
    // Clear stored code after sending
    selectedCodeStore = '';
    lastSelectionTime = 0;
    
    return true;
  }
  
  // Handle ping from popup
  if (message.type === 'PING') {
    sendResponse({ status: 'active' });
    return true;
  }
  
  // Handle AI API calls (placeholder for future implementation)
  if (message.type === 'CALL_AI_API') {
    handleAIAPICall(message.data)
      .then(result => sendResponse({ success: true, result }))
      .catch(error => sendResponse({ success: false, error: error.message }));
    
    return true; // Will respond asynchronously
  }
});

/**
 * Handle AI API calls
 * Replace this with your actual AI API integration
 */
async function handleAIAPICall(data: {
  code: string;
  context: 'testcase' | 'refactoring';
  prompt: string;
}): Promise<string> {
  console.log('AI API call requested:', data.context);
  
  try {
    // Example: OpenAI API call
    // Uncomment and configure when ready to integrate
    
    /*
    const response = await fetch('https://api.openai.com/v1/chat/completions', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${YOUR_API_KEY}`
      },
      body: JSON.stringify({
        model: 'gpt-4',
        messages: [
          {
            role: 'system',
            content: data.context === 'testcase'
              ? 'You are a helpful assistant that generates comprehensive test cases for code.'
              : 'You are a helpful assistant that refactors code for better performance and readability.'
          },
          {
            role: 'user',
            content: `${data.prompt}\n\nCode:\n${data.code}`
          }
        ],
        temperature: 0.7,
        max_tokens: 2000
      })
    });
    
    const result = await response.json();
    return result.choices[0].message.content;
    */
    
    // For now, return a simulated response
    return new Promise((resolve) => {
      setTimeout(() => {
        if (data.context === 'testcase') {
          resolve(`// Generated test cases for your code\n\ndescribe('Test Suite', () => {\n  it('should pass test 1', () => {\n    // Test implementation\n  });\n});`);
        } else {
          resolve(`// Refactored code\n\nconst optimizedFunction = () => {\n  // Improved implementation\n};`);
        }
      }, 1000);
    });
  } catch (error) {
    console.error('AI API call failed:', error);
    throw error;
  }
}

/**
 * Handle extension installation
 */
chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === 'install') {
    console.log('Codexter extension installed successfully!');
    
    // Open welcome page or show notification (optional)
    // chrome.tabs.create({ url: 'welcome.html' });
  } else if (details.reason === 'update') {
    console.log('Codexter extension updated to version:', chrome.runtime.getManifest().version);
  }
});

/**
 * Handle extension icon click (optional)
 */
chrome.action.onClicked.addListener((tab) => {
  console.log('Extension icon clicked on tab:', tab.id);
  
  // You could inject content script dynamically if needed
  if (tab.id) {
    chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: ['content.js']
    }).catch(error => {
      console.error('Failed to inject content script:', error);
    });
  }
});

/**
 * Clean up old stored code periodically (every 5 minutes)
 */
setInterval(() => {
  const now = Date.now();
  const fiveMinutes = 5 * 60 * 1000;
  
  if (selectedCodeStore && (now - lastSelectionTime) > fiveMinutes) {
    console.log('Clearing old stored code');
    selectedCodeStore = '';
    lastSelectionTime = 0;
  }
}, 60000); // Check every minute

// Export empty object to make this a module
export {};