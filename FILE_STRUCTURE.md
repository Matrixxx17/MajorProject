codexter/
│
├── 📄 popup.tsx                    # Main React component for popup UI
├── 📄 index.css                    # All styles for the extension
├── 📄 content.ts                   # Content script (runs on web pages)
├── 📄 background.ts                # Background service worker
├── 📄 types.ts                     # TypeScript type definitions
│
├── 📄 package.json                 # Project dependencies & scripts
├── 📄 tsconfig.json                # TypeScript configuration
├── 📄 .prettierrc                  # Code formatting rules
├── 📄 .gitignore                   # Git ignore patterns
│
├── 📄 README.md                    # Main documentation
├── 📄 QUICKSTART.md                # Quick start guide
├── 📄 FILE_STRUCTURE.md            # This file
│
├── 📁 assets/                      # Extension assets
│   └── icon.png                    # Extension icon (128x128px recommended)
│
├── 📁 node_modules/                # Dependencies (auto-generated)
├── 📁 .plasmo/                     # Plasmo cache (auto-generated)
└── 📁 build/                       # Build output (auto-generated)
    ├── chrome-mv3-dev/            # Development build
    └── chrome-mv3-prod/           # Production build