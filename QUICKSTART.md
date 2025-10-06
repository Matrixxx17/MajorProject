# 🚀 Quick Start Guide - Codexter

Get your Codexter extension up and running in 5 minutes!

## 📋 Prerequisites

Make sure you have:
- ✅ Node.js v18+ installed
- ✅ Chrome or Edge browser
- ✅ A code editor (VS Code recommended)

## 🎯 Step-by-Step Setup

### Step 1: Install Dependencies

```bash
npm install
```

This installs all required packages including React, Plasmo, and TypeScript.

### Step 2: Start Development Mode

```bash
npm run dev
```

This starts the Plasmo development server. You'll see output like:
```
🟣 Plasmo Browser Extension v0.88.0
✓ Ready in 2.5s
```

### Step 3: Load Extension in Chrome

1. Open Chrome and navigate to: `chrome://extensions/`
2. Enable **"Developer mode"** (toggle in top-right)
3. Click **"Load unpacked"**
4. Select the folder: `build/chrome-mv3-dev`
5. You should see the Codexter extension appear! 🎉

### Step 4: Test It Out!

1. **Click the Codexter icon** in your toolbar
2. Click **"Get Started"**
3. Choose **"Test Case Generation"** or **"Code Refactoring"**
4. Paste some code or select code from any webpage
5. Watch the magic happen! ✨

## 🎨 Your First Code Test

Try this sample code:

```javascript
function add(a, b) {
  return a + b;
}
```

1. Copy the code above
2. Open Codexter
3. Choose "Test Case Generation"
4. Paste the code
5. See the generated tests!

## 🌐 Test Code Selection from Webpages

1. Go to any coding website (GitHub, StackOverflow, etc.)
2. Select a code snippet
3. Open Codexter popup
4. The code is automatically attached! 🎯

## 🔧 Integrating Your AI API

### Option 1: OpenAI

Edit `background.ts` and add your API key:

```typescript
const response = await fetch('https://api.openai.com/v1/chat/completions', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer YOUR_OPENAI_API_KEY'
  },
  body: JSON.stringify({
    model: 'gpt-4',
    messages: [{
      role: 'user',
      content: `Generate test cases for:\n${data.code}`
    }]
  })
});
```

### Option 2: Anthropic Claude

```typescript
const response = await fetch('https://api.anthropic.com/v1/messages', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'x-api-key': 'YOUR_ANTHROPIC_API_KEY',
    'anthropic-version': '2023-06-01'
  },
  body: JSON.stringify({
    model: 'claude-3-opus-20240229',
    max_tokens: 2000,
    messages: [{
      role: 'user',
      content: `Generate test cases for:\n${data.code}`
    }]
  })
});
```

### Option 3: Custom Backend

```typescript
const response = await fetch('https://your-backend.com/api/code-assist', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer YOUR_TOKEN'
  },
  body: JSON.stringify({
    code: data.code,
    task: data.context
  })
});
```

## 📦 Building for Production

When you're ready to deploy:

```bash
# Build the extension
npm run build

# Package it
npm run package
```

Your production-ready extension will be in `build/chrome-mv3-prod/`

## 🎨 Customization Quick Tips

### Change Colors

In `index.css`, find:
```css
background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
```

Replace with your colors:
```css
background: linear-gradient(135deg, #FF6B6B 0%, #4ECDC4 100%);
```

### Modify Code Detection

In `content.ts`, add patterns:
```typescript
const codePatterns = [
  /your\s+pattern/,
  /another\s+pattern/
];
```

### Change Extension Name

In `package.json`:
```json
{
  "displayName": "Your Extension Name"
}
```

## ❓ Common Issues & Fixes

### Issue: Extension not loading
**Fix**: Make sure you selected the `build/chrome-mv3-dev` folder, not the root folder.

### Issue: Code not being detected
**Fix**: Check browser console (F12) for errors. Make sure the content script is loaded.

### Issue: Build errors
**Fix**: 
```bash
rm -rf node_modules .plasmo
npm install
npm run dev
```

### Issue: Changes not reflecting
**Fix**: Click the reload icon (🔄) on the extension card in `chrome://extensions/`

## 🎓 Next Steps

- ✅ Integrate with your AI API
- ✅ Customize the UI to match your brand
- ✅ Add more code detection patterns
- ✅ Implement chat history persistence
- ✅ Add keyboard shortcuts
- ✅ Create unit tests

## 📚 Useful Resources

- [Plasmo Documentation](https://docs.plasmo.com/)
- [Chrome Extension Docs](https://developer.chrome.com/docs/extensions/)
- [React Documentation](https://react.dev/)
- [TypeScript Handbook](https://www.typescriptlang.org/docs/)

## 💬 Need Help?

- Check the main README.md for detailed documentation
- Open an issue on GitHub
- Review the code comments in each file

---

**Happy Coding! 🚀**