# Market Digest

**Learn the market in 5 minutes a day.** Every morning Market Digest listens to trusted finance podcasts and scans the
big newsrooms, then explains what matters in plain English: the key points, the numbers, the jargon and the lesson
behind the news. It's built for people who are new to investing.

- **Website:** https://litaphsinam.github.io/market-digest/
- **Android app:** [download the latest APK](https://github.com/litaPhsinaM/market-digest/releases/latest)

## What's inside

- **Today**: the day's stories as short study cards, "Today in 60 seconds", a market strip and a quick quiz
- **Learn**: 24 short lessons from "what is a stock?" upwards, plus practice rounds by level
- **Play**: paper-trade a virtual $100,000, call where stocks go next, and compete on leaderboards (free sign-in)
- **Scorecard**: forecasts made on the shows, scored when their deadlines arrive
- **Glossary**: every term explained, with an example

Everything except Play works without an account. Signing in (email link, no password) syncs your streak and progress
across devices.

## Try the Android app

1. On your Android phone, open the [latest release](https://github.com/litaPhsinaM/market-digest/releases/latest) and
   download `MarketDigest-1.3.apk`.
2. Open the file. Android will ask you to allow installs from your browser ("Install unknown apps"); allow it once.
3. Tap **Install**, then open **Market Digest**.

The app shows the same content as the website and updates daily. It needs the internet the first time you open it;
after that, the last day you loaded is available offline. It's a test build, not from the Play Store, so Android may
show a "Play Protect" warning; choose **Install anyway** if you trust the source.

iPhone users: open the website in Safari and use **Share → Add to Home Screen**.

## Good to know

- Summaries are written by AI from public podcast episodes and newsroom headlines. They can contain mistakes, so
  check the original (linked on every story) before relying on a number.
- Market data is from Yahoo Finance and may be delayed.
- **Nothing here is financial advice.**
- Not affiliated with any show, newsroom or company mentioned. Creators who want a show removed can
  [open a request](https://github.com/litaPhsinaM/market-digest/issues/new?title=Removal%20request).

## For developers

```bash
python run.py               # daily run: fetch new episodes, summarize, build the site into site/
python run.py --build-only  # rebuild the site from saved summaries
```

The Android app (in `mobile/`) is a Capacitor wrapper that loads the live site:

```bash
python run.py --build-only
cd mobile && LIVE_URL=https://litaphsinam.github.io/market-digest/ npm run sync
cd android && ./gradlew assembleDebug   # → app/build/outputs/apk/debug/app-debug.apk
```
