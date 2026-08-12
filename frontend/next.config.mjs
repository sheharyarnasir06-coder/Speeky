/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: false,

  async headers() {
    return [
      {
        // MediaPipe wasm + .task models are ~29MB and content-addressed by
        // scripts/fetch-mediapipe-assets.mjs (pinned sha256 per file), so they are safe to
        // cache forever. Without this, every session re-validates 12MB of wasm.
        //
        // Deliberately NOT setting COOP/COEP here. `Cross-Origin-Embedder-Policy: require-corp`
        // is the only way to get SharedArrayBuffer and therefore MediaPipe's threaded wasm
        // build, but it also breaks every cross-origin resource that isn't CORP-annotated —
        // including backend-origin avatars and uploads. The vision pipeline is designed around
        // single-thread SIMD instead: it runs at most one model per frame at staggered rates
        // (see frontend/lib/vision/frameScheduler.ts), which keeps it inside the frame budget
        // without threads. Please don't "fix" this.
        source: "/mediapipe/:path*",
        headers: [
          {
            key: "Cache-Control",
            value: "public, max-age=31536000, immutable",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
