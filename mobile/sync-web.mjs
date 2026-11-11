// Copy the built site into the app, and write the Capacitor config.
// LIVE_URL=https://litaphsinam.github.io/market-digest/ makes the app load the live site (fresh content daily);
// without it the app runs the bundled snapshot, which is handy for testing before the site is published.
import { cpSync, rmSync, writeFileSync, existsSync } from "node:fs";

if (!existsSync("../site/index.html")) throw new Error("Build the site first: python run.py --build-only");
rmSync("www", { recursive: true, force: true });
cpSync("../site", "www", { recursive: true });

const live = process.env.LIVE_URL;
// Shown by the app instead of a raw browser error when the live site can't be reached (e.g. first launch offline).
writeFileSync("www/offline.html", `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Market Digest</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#111110;color:#f0efec;
font:16px/1.5 -apple-system,Roboto,sans-serif;text-align:center;padding:24px;box-sizing:border-box}
h1{font-size:1.3rem;margin:16px 0 8px}p{color:#c3c2b7;margin:0 0 24px}
button{font:inherit;font-weight:700;border:0;border-radius:99px;padding:12px 24px;background:#5cc0a2;color:#111110}</style>
</head><body><div><div style="font-size:44px">📡</div><h1>Can't reach Market Digest</h1>
<p>You may be offline. The app needs the internet to fetch today's stories.<br>Check your connection and try again.</p>
<button onclick="location.href='${live || "index.html"}'">Try again</button></div></body></html>
`);
const config = {
  appId: "io.github.litaphsinam.marketdigest",
  appName: "Market Digest",
  webDir: "www",
  ...(live ? { server: { url: live, androidScheme: "https", errorPath: "offline.html" } } : { server: { androidScheme: "https" } }),
  android: { backgroundColor: "#111110", adjustMarginsForEdgeToEdge: "auto" },
  plugins: {
    SplashScreen: { launchShowDuration: 900, backgroundColor: "#111110", showSpinner: false },
    StatusBar: { overlaysWebView: false, backgroundColor: "#111110", style: "DARK" },
  },
};
writeFileSync("capacitor.config.json", JSON.stringify(config, null, 2) + "\n");
console.log(live ? `App will load the live site: ${live}` : "App will use the bundled snapshot (no LIVE_URL set)");
