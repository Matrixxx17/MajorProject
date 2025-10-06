# 🔌 API Integration Guide

Complete guide to integrating AI APIs with your Codexter extension.

## 🎯 Overview

This guide shows you how to connect Codexter with various AI services for real code analysis, test generation, and refactoring.

## 📍 Where to Add API Integration

All API integration happens in the `background.ts` file, specifically in the `handleAIAPICall` function.

## 🤖 Option 1: OpenAI (GPT-4)

### Setup

1. Get API key from [OpenAI Platform](https://platform.openai.com/api-keys)
2. Update `background.ts`:

```typescript
async function handleAIAPICall(data: {
  code: string;
  context: 'testcase' | 'refactoring';
  prompt: string;
}): Promise<string> {
  const API_KEY = 'sk-...'; // Your OpenAI API key
  
  const systemPrompt = data.context === 'testcase'
    ? 'You are an expert software tester. Generate comprehensive, production-ready test cases using popular testing frameworks.'
    : 'You are an expert software engineer. Refactor code to improve readability, performance, and maintainability while preserving functionality.';

  try {
    const response = await fetch('https://api.openai.com/v1/chat/completions', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${API_KEY}`
      },
      body: JSON.stringify({
        model: 'gpt-4',
        messages: [
          {
            role: 'system',
            content: systemPrompt
          },
          {
            role: 'user',
            content: `${data.prompt}\n\nCode:\n\`\`\`\n${data.code}\n\`\`\``
          }
        ],
        temperature: 0.7,
        max_tokens: 2000
      })
    });

    if (!response.ok) {
      throw new Error(`API error: ${response.statusText}`);
    }

    const result = await response.json();
    return result.choices[0].message.content;
  } catch (error) {
    console.error('OpenAI API call failed:', error);
    throw error;
  }
}
```

### Cost Estimation
- GPT-4: ~$0.03 per 1K input tokens, ~$0.06 per 1K output tokens
- Average query: 500 tokens in, 1000 tokens out = ~$0.075 per request

## 🧠 Option 2: Anthropic Claude

### Setup

1. Get API key from [Anthropic Console](https://console.anthropic.com/)
2. Update `background.ts`:

```typescript
async function handleAIAPICall(data: {
  code: string;
  context: 'testcase' | 'refactoring';
  prompt: string;
}): Promise<string> {
  const API_KEY = 'sk-ant-...'; // Your Anthropic API key
  
  const systemPrompt = data.context === 'testcase'
    ? 'You are an expert software tester specializing in comprehensive test case generation.'
    : 'You are an expert at refactoring code to improve quality while maintaining functionality.';

  try {
    const response = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': API_KEY,
        'anthropic-version': '2023-06-01'
      },
      body: JSON.stringify({
        model: 'claude-3-5-sonnet-20241022',
        max_tokens: 4000,
        system: systemPrompt,
        messages: [
          {
            role: 'user',
            content: `${data.prompt}\n\nCode to analyze:\n\`\`\`\n${data.code}\n\`\`\``
          }
        ]
      })
    });

    if (!response.ok) {
      throw new Error(`API error: ${response.statusText}`);
    }

    const result = await response.json();
    return result.content[0].text;
  } catch (error) {
    console.error('Anthropic API call failed:', error);
    throw error;
  }
}
```

### Cost Estimation
- Claude 3.5 Sonnet: ~$3 per million input tokens, ~$15 per million output tokens
- Average query: ~$0.005 per request

## 🌐 Option 3: Custom Backend API

### Setup

Create your own backend that interfaces with any AI service.

```typescript
async function handleAIAPICall(data: {
  code: string;
  context: 'testcase' | 'refactoring';
  prompt: string;
}): Promise<string> {
  const BACKEND_URL = 'https://your-backend.com/api/code-assist';
  const AUTH_TOKEN = 'your-auth-token';

  try {
    const response = await fetch(BACKEND_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${AUTH_TOKEN}`
      },
      body: JSON.stringify({
        code: data.code,
        context: data.context,
        prompt: data.prompt,
        userId: 'user-id', // Optional: track usage
        timestamp: Date.now()
      })
    });

    if (!response.ok) {
      throw new Error(`Backend error: ${response.statusText}`);
    }

    const result = await response.json();
    return result.analysis || result.response || result.content;
  } catch (error) {
    console.error('Backend API call failed:', error);
    throw error;
  }
}
```

### Backend Example (Node.js/Express)

```javascript
// backend/server.js
const express = require('express');
const { OpenAI } = require('openai');

const app = express();
app.use(express.json());

const openai = new OpenAI({
  apiKey: process.env.OPENAI_API_KEY
});

app.post('/api/code-assist', async (req, res) => {
  try {
    const { code, context, prompt } = req.body;
    
    const completion = await openai.chat.completions.create({
      model: 'gpt-4',
      messages: [
        {
          role: 'system',
          content: context === 'testcase' 
            ? 'Generate test cases' 
            : 'Refactor code'
        },
        {
          role: 'user',
          content: `${prompt}\n\n${code}`
        }
      ]
    });
    
    res.json({
      analysis: completion.choices[0].message.content
    });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

app.listen(3000);
```

## 🔒 Option 4: Secure API Key Storage

### Using Chrome Storage API

Store API keys securely using Chrome's storage:

```typescript
// In popup.tsx - Settings screen
async function saveApiKey(apiKey: string) {
  await chrome.storage.local.set({ apiKey });
}

// In background.ts
async function getApiKey(): Promise<string> {
  const result = await chrome.storage.local.get('apiKey');
  return result.apiKey || '';
}

async function handleAIAPICall(data: any): Promise<string> {
  const apiKey = await getApiKey();
  
  if (!apiKey) {
    throw new Error('API key not configured. Please add it in settings.');
  }
  
  // Use apiKey in your API call
  const response = await fetch('...', {
    headers: {
      'Authorization': `Bearer ${apiKey}`
    }
  });
  
  // ...
}
```

### Add Settings Screen in popup.tsx

```typescript
// Add to popup.tsx
const [screen, setScreen] = useState<Screen>("welcome");
// Add "settings" to Screen type

// Settings screen JSX
{screen === "settings" && (
  <div className="popup-card settings-screen">
    <h2>Settings</h2>
    <div className="setting-group">
      <label>API Key</label>
      <input
        type="password"
        value={apiKey}
        onChange={(e) => setApiKey(e.target.value)}
        placeholder="Enter your API key"
      />
      <button onClick={() => saveApiKey(apiKey)}>
        Save
      </button>
    </div>
  </div>
)}
```

## ⚡ Option 5: Streaming Responses

For real-time streaming (like ChatGPT):

```typescript
async function handleAIAPICallStreaming(data: any): Promise<void> {
  const response = await fetch('https://api.openai.com/v1/chat/completions', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${API_KEY}`
    },
    body: JSON.stringify({
      model: 'gpt-4',
      messages: [...],
      stream: true // Enable streaming
    })
  });

  const reader = response.body?.getReader();
  const decoder = new TextDecoder();
  let fullResponse = '';

  while (true) {
    const { done, value } = await reader!.read();
    if (done) break;

    const chunk = decoder.decode(value);
    const lines = chunk.split('\n').filter(line => line.trim() !== '');

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const data = line.slice(6);
        if (data === '[DONE]') continue;

        try {
          const parsed = JSON.parse(data);
          const content = parsed.choices[0]?.delta?.content || '';
          fullResponse += content;

          // Send partial response to popup
          chrome.runtime.sendMessage({
            type: 'STREAMING_RESPONSE',
            content: fullResponse,
            isComplete: false
          });
        } catch (e) {
          // Skip invalid JSON
        }
      }
    }
  }

  // Send final response
  chrome.runtime.sendMessage({
    type: 'STREAMING_RESPONSE',
    content: fullResponse,
    isComplete: true
  });
}
```

## 🎯 Testing Your Integration

### 1. Test with Simple Code

```javascript
function add(a, b) {
  return a + b;
}
```

### 2. Test with Complex Code

```typescript
class UserService {
  private users: User[] = [];
  
  async createUser(data: UserData): Promise<User> {
    const user = new User(data);
    this.users.push(user);
    return user;
  }
}
```

### 3. Check Error Handling

Test what happens when:
- API key is invalid
- Network is offline
- API rate limit is hit
- Response is too long

## 🐛 Debugging API Calls

Add comprehensive logging:

```typescript
async function handleAIAPICall(data: any): Promise<string> {
  console.log('🔵 API Call Started', {
    context: data.context,
    codeLength: data.code.length,
    timestamp: new Date().toISOString()
  });

  try {
    const startTime = Date.now();
    const response = await fetch(/* ... */);
    const duration = Date.now() - startTime;

    console.log('🟢 API Call Successful', {
      duration: `${duration}ms`,
      status: response.status
    });

    const result = await response.json();
    console.log('📦 Response received', {
      length: result.content?.length || 0
    });

    return result.content;
  } catch (error) {
    console.error('🔴 API Call Failed', {
      error: error.message,
      stack: error.stack
    });
    throw error;
  }
}
```

## 💰 Cost Management

### Add Usage Tracking

```typescript
let dailyUsage = {
  requests: 0,
  tokens: 0,
  date: new Date().toDateString()
};

function trackUsage(tokens: number) {
  const today = new Date().toDateString();
  
  if (dailyUsage.date !== today) {
    dailyUsage = { requests: 0, tokens: 0, date: today };
  }
  
  dailyUsage.requests++;
  dailyUsage.tokens += tokens;
  
  console.log('Usage Today:', dailyUsage);
  
  // Save to storage
  chrome.storage.local.set({ usage: dailyUsage });
}
```

## ✅ Best Practices

1. **Never hardcode API keys** - Use environment variables or Chrome storage
2. **Implement rate limiting** - Prevent excessive API calls
3. **Add retry logic** - Handle temporary failures
4. **Cache responses** - Save common queries
5. **Handle errors gracefully** - Show user-friendly messages
6. **Log everything** - Makes debugging easier
7. **Test thoroughly** - Try edge cases

---

**Ready to power up your extension with AI!** 🚀