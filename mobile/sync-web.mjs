// Copy the built site into the app, and write the Capacitor config.
// LIVE_URL=https://litaphsinam.github.io/market-digest/ makes the app load the live site (fresh content daily);
// without it the app runs the bundled snapshot, which is handy for testing before the site is published.
import { cpSync, rmSync, writeFileSync, existsSync } from "node:fs";

if (!existsSync("../site/index.html")) throw new Error("Build the site first: python run.py --build-only");
rmSync("www", { recursive: true, force: true });
cpSync("../site", "www", { recursive: true });

const live = process.env.LIVE_URL;
const config = {
  appId: "io.github.litaphsinam.marketdigest",
  appName: "Market Digest",
  webDir: "www",
  ...(live ? { server: { url: live, androidScheme: "https" } } : { server: { androidScheme: "https" } }),
  android: { backgroundColor: "#111110" },
  plugins: {
    SplashScreen: { launchShowDuration: 900, backgroundColor: "#111110", showSpinner: false },
    StatusBar: { overlaysWebView: false, backgroundColor: "#111110", style: "DARK" },
  },
};
writeFileSync("capacitor.config.json", JSON.stringify(config, null, 2) + "\n");
console.log(live ? `App will load the live site: ${live}` : "App will use the bundled snapshot (no LIVE_URL set)");
