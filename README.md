# Say Cheese Pizza

A responsive homepage for Say Cheese Pizza in Maiden Gully, Victoria. Built with React and Vite, with local Barlow Condensed and Inter fonts, original generated pizza imagery, and an accessible pickup-order planner.

## Develop

Use Node.js 24 (validated with 24.19.0) and npm. Vite requires Node 20.19+ or 22.12+.

```sh
cd /workspace/SAY-CHEESE-PIZZA
export npm_config_cache=/workspace/.cache/npm
npm ci --no-audit --no-fund
npm run dev -- --port 5173 --strictPort
```

Use the existing checkout in the isolated cloud environment. There is no need to create a Git worktree. No environment variables, credentials, database, or backend service are required.

## Production build

```sh
npm run build
npm run preview -- --port 4173 --strictPort
```

The static build is written to `dist/`.

## GitHub Pages

```sh
npm run build:pages
```

This builds assets for the repository path `/SAY-CHEESE-PIZZA/`. The compiled site can be published on the `gh-pages` branch. In GitHub repository settings, choose **Pages → Deploy from a branch → gh-pages → / (root) → Save**.

Once GitHub's deployment finishes, its Pages address is `https://xavierpring1-svg.github.io/SAY-CHEESE-PIZZA/`. The setting must be enabled before this address serves the site.

## Content and behaviour

- The business name, address, phone number, review score, and review excerpts come from the supplied brief.
- The pizza names, ingredients, and prices are an explicitly labelled **sample menu**. Replace `pizzas` in `src/App.jsx` with the shop's verified menu before publication. The images are generated illustrations of pizza, not photos of the shop's actual menu or premises.
- The order planner filters pizzas, saves item IDs and quantities in browser storage, updates AUD estimates, and lets visitors copy their order list or call the shop. It does not transmit orders or take payments.
- The single location illustration supports zoom controls and links to Google Maps for real directions. It is not a geographic map.
- Only the supplied 10 pm closing time is shown; visitors are asked to call for the day's opening hours.
- Fonts and images are served locally, with no runtime image CDN dependency.

## Validation

The production build and Chromium checks cover desktop/mobile rendering, image loading, menu categories and expansion, adding/removing pizzas, totals and quantities, browser-storage persistence, clipboard behaviour, keyboard focus trapping/restoration, Escape dismissal, mobile navigation, and phone/direction links.

There is no online checkout, reservation backend, newsletter service, or analytics integration.
