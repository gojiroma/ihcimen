#!/bin/bash
# Builds TodayH1.app from the SwiftPM executable target.
set -euo pipefail
cd "$(dirname "$0")"

APP_NAME="TodayH1"
BUILD_DIR=".build/release"
APP_BUNDLE="${APP_NAME}.app"

echo "Building ${APP_NAME}..."
swift build -c release

rm -rf "${APP_BUNDLE}"
mkdir -p "${APP_BUNDLE}/Contents/MacOS"
mkdir -p "${APP_BUNDLE}/Contents/Resources"

cp "${BUILD_DIR}/${APP_NAME}" "${APP_BUNDLE}/Contents/MacOS/${APP_NAME}"
cp Info.plist "${APP_BUNDLE}/Contents/Info.plist"

codesign --force --deep --sign - "${APP_BUNDLE}"

echo "Built ${APP_BUNDLE}"
echo "Run: open ${APP_BUNDLE}"
