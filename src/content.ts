/**
 * Content Script for Codexter Extension
 * Detects code selection on web pages and sends it to the popup
 */

console.log('Codexter content script loaded');

// Listen for text selection on mouseup
document.addEventListener('mouseup', handleTextSelection);

// Listen for keyboard shortcuts (Ctrl/Cmd + C)
document.addEventListener('keydown', handleKeyboardShortcut);

// Listen for selection changes
document.addEventListener('selectionchange', debounce(handleSelectionChange, 300));

/**
 * Handle text selection on mouse up
 */
function handleTextSelection(): void {
  const selection = window.getSelection();
  const selectedText = selection?.toString().trim();
  
  if (selectedText && selectedText.length > 0) {
    const looksLikeCode = detectIfCode(selectedText);
    
    if (looksLikeCode) {
      sendCodeToPopup(selectedText);
    }
  }
}

/**
 * Handle keyboard shortcut (Ctrl/Cmd + C)
 */
function handleKeyboardShortcut(e: KeyboardEvent): void {
  if ((e.ctrlKey || e.metaKey) && e.key === 'c') {
    setTimeout(() => {
      const selection = window.getSelection();
      const selectedText = selection?.toString().trim();
      
      if (selectedText && selectedText.length > 0) {
        const looksLikeCode = detectIfCode(selectedText);
        
        if (looksLikeCode) {
          sendCodeToPopup(selectedText);
        }
      }
    }, 100);
  }
}

/**
 * Handle selection change events
 */
function handleSelectionChange(): void {
  const selection = window.getSelection();
  const selectedText = selection?.toString().trim();
  
  if (selectedText && selectedText.length > 10) {
    const looksLikeCode = detectIfCode(selectedText);
    
    if (looksLikeCode) {
      // Visual feedback (optional)
      console.log('Code detected:', selectedText.substring(0, 50) + '...');
    }
  }
}

/**
 * Send selected code to popup via background script
 */
function sendCodeToPopup(code: string): void {
  try {
    chrome.runtime.sendMessage({
      type: 'CODE_SELECTED',
      code: code,
      timestamp: Date.now(),
      url: window.location.href
    });
    
    console.log('Code sent to popup:', code.length, 'characters');
  } catch (error) {
    console.error('Error sending code to popup:', error);
  }
}

/**
 * Detect if selected text is code using multiple heuristics
 */
function detectIfCode(text: string): boolean {
  // Code patterns for different languages
  const codePatterns = [
    // JavaScript/TypeScript
    /function\s+\w+\s*\(/i,
    /const\s+\w+\s*=/,
    /let\s+\w+\s*=/,
    /var\s+\w+\s*=/,
    /=>\s*\{?/,
    /import\s+.*from/,
    /export\s+(default|const|class|function)/,
    /interface\s+\w+/,
    /type\s+\w+\s*=/,
    
    // Python
    /def\s+\w+\s*\(/,
    /class\s+\w+\s*:/,
    /import\s+\w+/,
    /from\s+\w+\s+import/,
    
    // Java/C#/C++
    /public\s+(class|interface|static)/,
    /private\s+\w+/,
    /protected\s+\w+/,
    /void\s+\w+\s*\(/,
    /namespace\s+\w+/,
    
    // HTML/JSX
    /<\w+[^>]*>/,
    /<\/\w+>/,
    /className=/,
    /onClick=/,
    
    // CSS
    /\.\w+\s*\{/,
    /#\w+\s*\{/,
    /@media\s+/,
    /:\s*\w+\s*;/,
    
    // SQL
    /SELECT\s+.*FROM/i,
    /INSERT\s+INTO/i,
    /UPDATE\s+.*SET/i,
    /DELETE\s+FROM/i,
    
    // Common patterns
    /\w+\s*\([^)]*\)\s*\{/,  // Function calls with blocks
    /if\s*\([^)]+\)\s*\{/,    // If statements
    /for\s*\([^)]+\)\s*\{/,   // For loops
    /while\s*\([^)]+\)\s*\{/, // While loops
    /try\s*\{/,               // Try blocks
    /catch\s*\(/,             // Catch blocks
  ];
  
  // Check if text matches any code pattern
  const hasCodePattern = codePatterns.some(pattern => pattern.test(text));
  
  // Code-like characteristics
  const hasCodeCharacteristics = (
    // Has brackets
    (text.includes('{') && text.includes('}')) ||
    (text.includes('(') && text.includes(')')) ||
    (text.includes('[') && text.includes(']')) ||
    
    // Has code symbols
    text.includes(';') ||
    text.includes('//') ||
    text.includes('/*') ||
    text.includes('*/') ||
    text.includes('=>') ||
    text.includes('===') ||
    text.includes('!==') ||
    
    // Has indentation (2+ spaces at start of lines)
    /^\s{2,}/m.test(text) ||
    
    // Multiple lines with consistent indentation
    (text.split('\n').length > 2 && /^\s+/m.test(text))
  );
  
  // Check if selected from code elements
  const selection = window.getSelection();
  const anchorNode = selection?.anchorNode;
  const parentElement = anchorNode?.parentElement;
  
  const isFromCodeElement = parentElement?.closest(
    'pre, code, .code, .CodeMirror, .monaco-editor, .ace_editor, ' +
    '[class*="editor"], [class*="code"], [class*="snippet"], ' +
    '.highlight, .hljs, .CodeMirror-code'
  ) !== null;
  
  // Check if page is a code-related site
  const isCodeSite = /github|stackoverflow|codepen|jsfiddle|codesandbox|repl\.it|leetcode|hackerrank/i.test(
    window.location.hostname
  );
  
  // Additional weight for code sites
  const codeScore = (
    (hasCodePattern ? 2 : 0) +
    (hasCodeCharacteristics ? 1 : 0) +
    (isFromCodeElement ? 2 : 0) +
    (isCodeSite ? 1 : 0)
  );
  
  // Return true if score is high enough
  return codeScore >= 2;
}

/**
 * Debounce function to limit rate of function calls
 */
function debounce<T extends (...args: any[]) => any>(
  func: T,
  wait: number
): (...args: Parameters<T>) => void {
  let timeout: NodeJS.Timeout | null = null;
  
  return function executedFunction(...args: Parameters<T>) {
    const later = () => {
      timeout = null;
      func(...args);
    };
    
    if (timeout) {
      clearTimeout(timeout);
    }
    timeout = setTimeout(later, wait);
  };
}

/**
 * Listen for messages from popup or background script
 */
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'GET_SELECTED_CODE') {
    const selection = window.getSelection();
    const selectedText = selection?.toString().trim();
    sendResponse({ code: selectedText || '' });
    return true;
  }
  
  if (message.type === 'PING') {
    sendResponse({ status: 'active' });
    return true;
  }
});

// Export empty object to make this a module
export {};