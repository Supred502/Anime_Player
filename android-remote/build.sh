#!/bin/bash
# Builds and signs AnimePlayerRemote.apk without Gradle -- just the SDK's own
# build-tools (aapt2, d8, zipalign, apksigner) plus a JDK for javac. See
# MainActivity.java's docstring for what this app actually is (a thin WebView
# shell around the same remote page animeplayer/remote/server.py serves).
#
# Requires: ANDROID_SDK_ROOT pointing at an SDK with build-tools + a platform,
# and JAVA_HOME pointing at a real JDK (javac, not just a JRE).
set -euo pipefail
cd "$(dirname "$0")"

: "${ANDROID_SDK_ROOT:?Set ANDROID_SDK_ROOT to your Android SDK path}"
: "${JAVA_HOME:?Set JAVA_HOME to a JDK (needs javac, not just a JRE)}"
BUILD_TOOLS="$(ls -d "$ANDROID_SDK_ROOT"/build-tools/*/ | sort -V | tail -1)"
PLATFORM="$(ls -d "$ANDROID_SDK_ROOT"/platforms/*/ | sort -V | tail -1)"

# The signing keystore has to survive across builds in a real dir outside
# build/, not just skip regeneration inside it -- confirmed the hard way:
# `rm -rf build` below wiped it every time regardless of the "if missing"
# check further down, so every rebuild silently signed with a brand new key.
# Android then refuses to install that as an update over what's already on
# a phone (different signing identity), which looks like "the new APK won't
# install" with no useful error explaining why.
mkdir -p signing
if [ ! -f signing/debug.keystore ]; then
  echo "== generating signing key (first build only) =="
  "$JAVA_HOME/bin/keytool" -genkeypair -v \
    -keystore signing/debug.keystore \
    -alias animeplayerremote \
    -keyalg RSA -keysize 2048 -validity 10000 \
    -storepass animeplayer -keypass animeplayer \
    -dname "CN=Anime Player Remote, OU=Personal, O=Personal, L=Unknown, S=Unknown, C=US"
fi

rm -rf build
mkdir -p build/gen build/apk build/classes

echo "== compiling resources =="
"$BUILD_TOOLS/aapt2" compile --dir res -o build/compiled_res.zip

echo "== linking resources =="
"$BUILD_TOOLS/aapt2" link \
  -o build/apk/base.apk \
  -I "$PLATFORM/android.jar" \
  --manifest AndroidManifest.xml \
  --java build/gen \
  build/compiled_res.zip \
  --auto-add-overlay

echo "== compiling java =="
"$JAVA_HOME/bin/javac" \
  -classpath "$PLATFORM/android.jar" \
  -d build/classes \
  src/com/supred/animeplayerremote/MainActivity.java \
  build/gen/com/supred/animeplayerremote/R.java

echo "== dexing =="
"$BUILD_TOOLS/d8" \
  --output build/apk \
  --lib "$PLATFORM/android.jar" \
  $(find build/classes -name "*.class")

echo "== packaging =="
cp build/apk/base.apk build/apk/unsigned.apk
(cd build/apk && zip -j unsigned.apk classes.dex)

echo "== zipaligning =="
"$BUILD_TOOLS/zipalign" -f -p 4 build/apk/unsigned.apk build/apk/aligned.apk

echo "== signing =="
"$BUILD_TOOLS/apksigner" sign \
  --ks signing/debug.keystore \
  --ks-pass pass:animeplayer \
  --ks-key-alias animeplayerremote \
  --out build/AnimePlayerRemote.apk \
  build/apk/aligned.apk

echo "== done: build/AnimePlayerRemote.apk =="
"$BUILD_TOOLS/apksigner" verify build/AnimePlayerRemote.apk
