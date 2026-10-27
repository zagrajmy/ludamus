// NOTE: `wrangler types` would generate this from wrangler.json along with
// the whole runtime, which tsconfig already takes from workers-types.
declare namespace Cloudflare {
  interface Exports {
    default: Fetcher;
  }
}
