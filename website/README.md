# Carpathian OS website

Buildless HTML, CSS and JavaScript. Original mountain SVG artwork and actual development VM photography. No framework, analytics, third-party fonts or external runtime dependencies.

From this directory, preview with `python3 -m http.server 8788 --directory dist` and open `http://127.0.0.1:8788`. This development server does not apply Cloudflare response headers.

Validate the static deployment with `wrangler deploy --dry-run`. Deploy with `wrangler deploy` from an authenticated Cloudflare CLI session, then verify the custom domain. `wrangler.jsonc` declares the `carpathianos.com` custom domain; no credentials belong here.

Set `config.githubUrl` in `dist/main.js` only once the curated repository is public. Replace development download status with a real release URL and verified checksum when available. The experimental installer is not qualified for daily use.

The desktop image is an actual Alpine Xorg development VM capture. Mountain artwork is original SVG brand imagery. Neither is a claim of release qualification.
