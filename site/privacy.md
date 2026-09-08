# Kami privacy

Kami has no service that receives your documents. It runs where you install it; if you use a hosted AI assistant, that provider’s privacy terms also apply.

HTML version: <https://kami.tw93.fun/privacy>

## This site

kami.tw93.fun is a static deploy of the public repository, hosted on Vercel. It sets no cookies, runs no analytics, and loads no third-party scripts, fonts, or images: every asset, including the JetBrains Mono and TsangerJinKai typefaces, is served from this domain. There is no tag manager or tracking pixel.

One value is stored in your browser: `kami-lang`, written to `localStorage` when you pick a language from the switcher, so the site stops redirecting you away from your choice. It never leaves the browser, and clearing site data removes it.

Vercel, as the host, records standard server access logs, including IP address, request path, and user agent, for delivery and abuse prevention. Those logs are Vercel's, held under their retention policy, and are not exported, joined with anything, or used to build a profile. Downloads of the release package are served by GitHub and are subject to GitHub's own logging.

## The skill

The Kami skill, templates, scripts, and MCP server run in the environment where you install them. They contain no telemetry, crash reporting, or license check. A version check contacts GitHub at most once a day and stores a local cache marker; it sends no document or task content.

Two behaviours are worth stating plainly. First, rendering follows the document you give it: if your HTML references a remote image, stylesheet, or font, the renderer fetches it with your machine's network access, exactly as a browser would, so only render HTML you trust. Second, the MCP server reads and writes files with the permissions of the process you started it with; it exposes rendering and checking tools, not a sandbox.

Whether your document text reaches a model provider is a property of the agent you use Kami inside, not of Kami. If you drive it with a hosted assistant, that assistant's privacy terms apply to the conversation. Kami adds no additional destination.

## AI access policy

Search engines, AI answer engines, and assistants acting for a user are welcome to read this site, quote it, and learn from it: the documentation exists to be found, and everything here is MIT licensed source you can read directly on GitHub. That permission is stated as a machine-readable content signal in [robots.txt](https://kami.tw93.fun/robots.txt). Bulk archive crawlers that return no reader to the source are disallowed there by name, which is a bandwidth judgement rather than a hostile one.

Questions about any of this, or a request to have a server log entry looked up or removed, go to the [contact page](https://kami.tw93.fun/contact).

## Elsewhere

[Home](https://kami.tw93.fun/) · [Developers](https://kami.tw93.fun/developers) · [About](https://kami.tw93.fun/about) · [Contact](https://kami.tw93.fun/contact) · [Source](https://github.com/tw93/kami)
