#!/bin/zsh
set -euo pipefail
PROJECT_DIR="${0:A:h:h}"
cd "$PROJECT_DIR"
swift build -c release
APP_DIR="$PROJECT_DIR/dist/迎声.app"
mkdir -p "$APP_DIR/Contents/MacOS" "$APP_DIR/Contents/Resources"
cp .build/release/WelcomeMac "$APP_DIR/Contents/MacOS/WelcomeMac"
rsync -a --delete --exclude '__pycache__' backend/ "$APP_DIR/Contents/Resources/backend/"
print -rn -- "$PROJECT_DIR" > "$APP_DIR/Contents/Resources/runtime-path.txt"
cat > "$APP_DIR/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleName</key><string>迎声</string>
<key>CFBundleDisplayName</key><string>迎声 · 直播欢迎助手</string>
<key>CFBundleIdentifier</key><string>local.douyin.welcome</string>
<key>CFBundleExecutable</key><string>WelcomeMac</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>0.1.0</string>
<key>CFBundleVersion</key><string>1</string>
<key>LSMinimumSystemVersion</key><string>14.0</string>
<key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
codesign --force --deep --sign - "$APP_DIR"
print "已构建：$APP_DIR"
