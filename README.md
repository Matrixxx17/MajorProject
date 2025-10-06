# 🚀 Codexter - AI Code Assistant

An intelligent Chrome extension for AI-powered code testing and refactoring. Built with Plasmo, React, and TypeScript.

## ✨ Features

- **🎯 Smart Code Detection**: Automatically detects code snippets selected on any webpage
- **🧪 Test Case Generation**: Generate comprehensive test cases for your code
- **🔧 Code Refactoring**: Get intelligent suggestions to improve your code
- **💬 Chat Interface**: ChatGPT-like interface for interactive code assistance
- **📝 Context Switching**: Seamlessly switch between test generation and refactoring
- **💾 Chat History**: Maintains separate chat histories for each context
- **🎨 Beautiful UI**: Modern, gradient-based design with smooth animations

## 🛠️ Tech Stack

- **Framework**: Plasmo (Chrome Extension Framework)
- **Frontend**: React 18 + TypeScript
- **Styling**: Custom CSS with modern animations
- **Browser APIs**: Chrome Extension APIs (Manifest V3)

## 📦 Installation

### Prerequisites

- Node.js (v18 or higher)
- npm or yarn
- Chrome/Edge browser

### Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/codexter.git
   cd codexter
   ```

2. **Install dependencies**
   ```bash
   npm install
   ```

3. **Start development server**
   ```bash
   npm run dev
   ```

4. **Load the extension in Chrome**
   - Open Chrome and go to `chrome://extensions/`
   - Enable "Developer mode" (top right)
   - Click "Load unpacked"
   - Select the `build/chrome-mv3-dev` folder

## 🚀 Usage

### Getting Started

1. **Click the Codexter icon** in your browser toolbar
2. **Welcome Screen**: Click "Get Started"
3. **Choose Your Task**: Select either "Test Case Generation" or "Code Refactoring"
4. **Start Chatting**: Enter your code or select code from any webpage

### Selecting Code from Webpages

The extension automatically detects when you select code on any webpage:

1. Highlight any code snippet on a webpage
2. The extension will detect it automatically
3. Open the extension popup - the code will be attached
4. Add your instructions and send!

### Supported Code Detection

Codexter intelligently detects code from:
- Code editors (Monaco, CodeMirror, Ace)
- `<pre>` and `<code>` HTML elements
- GitHub, StackOverflow, CodePen, JSFiddle
- Any text with code-like patterns

## 📁 Project Structure

```
codexter/
├── popup.tsx              # Main popup component
├── index.css             # Styles for the popup
├── content.ts            # Content script for code detection
├── background.ts         # Background service worker
├── package.json          # Dependencies and scripts
├── tsconfig.json         # TypeScript configuration
├── assets/
│   └── icon.png         # Extension icon
└── README.md            # This file
```

## 🔧 Configuration

### API Integration

To integrate with your AI API, modify the `handleAIAPICall` function in `background.ts`:

```typescript
async function handleAIAPICall(data: {
  code: string;
  context: 'testcase' | 'refactoring';
  prompt: string;
}): Promise<string> {
  const response = await fetch('YOUR_API_ENDPOINT', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${YOUR_API_KEY}`
    },
    body: JSON.stringify({
      code: data.code,
      task: data.context,
      prompt: data.prompt
    })
  });
  
  const result = await response.json();
  return result.content;
}
```

### Supported APIs

You can integrate with:
- OpenAI GPT-4
- Anthropic Claude
- Google PaLM
- Custom backend API

## 🎨 Customization

### Changing Colors

Edit the gradient colors in `index.css`:

```css
/* Change the main gradient */
.popup-container {
  background: linear-gradient(135deg, #YOUR_COLOR1 0%, #YOUR_COLOR2 100%);
}
```

### Modifying Code Detection

Adjust code detection patterns in `content.ts`:

```typescript
const codePatterns = [
  /your\s+custom\s+pattern/,
  // Add more patterns
];
```

## 📝 Build for Production

1. **Build the extension**
   ```bash
   npm run build
   ```

2. **Package the extension**
   ```bash
   npm run package
   ```

3. **The packaged extension** will be in the `build/chrome-mv3-prod` folder

## 🐛 Troubleshooting

### Extension not detecting code
- Make sure the content script is loaded (check console)
- Verify code detection patterns match your use case
- Check browser console for errors

### Popup not receiving selected code
- Ensure background service worker is active
- Check message passing in browser DevTools
- Verify permissions in manifest

### Build errors
- Clear node_modules and reinstall: `rm -rf node_modules && npm install`
- Clear Plasmo cache: `rm -rf .plasmo`
- Update dependencies: `npm update`

## 🤝 Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Commit your changes: `git commit -m 'Add amazing feature'`
4. Push to the branch: `git push origin feature/amazing-feature`
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgments

- Built with [Plasmo](https://www.plasmo.com/)
- Icons from your assets folder
- Inspired by modern AI coding assistants

## 📧 Contact

For questions or support, please open an issue on GitHub.

---

**Made with ❤️ for developers**