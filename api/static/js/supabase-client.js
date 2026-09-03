// One Supabase client per page load, shared by every other script on the
// page (guard.js, api-client.js, and the page-specific script). Must be
// loaded after config.js (defines window.APP_CONFIG) and the Supabase CDN
// script, before anything that references `sb`.
//
// IMPORTANT CONTEXT FOR "Failed to fetch" WITH NOTHING IN THE SERVER LOGS:
// sb.auth.signUp() / signInWithPassword() call Supabase's Auth API directly
// from the browser — they never touch our FastAPI backend at all. So a
// broken sign-up will never show up in `uvicorn`'s output; the real error
// is always in the browser's own console/Network tab, not the server's.
// The single most common cause of a network-level "Failed to fetch" here
// is SUPABASE_URL still being the literal placeholder from .env.example
// (or otherwise wrong), so the browser can't resolve/reach it at all.
// This file checks for that specifically and fails loudly on-page instead
// of letting every later call fail with a cryptic message and no context.

function looksUnconfigured(value) {
  return !value || /your-project|your-anon-key/i.test(value);
}

function showConfigError(message) {
  console.error(`[Pharma RAG] ${message}`);
  const render = () => {
    const banner = document.createElement('div');
    banner.textContent = message;
    banner.style.cssText =
      'position:fixed;top:0;left:0;right:0;z-index:9999;background:#D70015;color:#fff;' +
      'padding:0.75rem 1rem;font:14px -apple-system,BlinkMacSystemFont,sans-serif;text-align:center;';
    document.body.prepend(banner);
    document.body.hidden = false; // otherwise the banner is invisible on guarded pages
  };
  document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', render) : render();
}

let sb;

if (looksUnconfigured(window.APP_CONFIG?.SUPABASE_URL) || looksUnconfigured(window.APP_CONFIG?.SUPABASE_ANON_KEY)) {
  showConfigError(
    'Configuration error: SUPABASE_URL / SUPABASE_ANON_KEY are missing or still placeholder values. ' +
      'Set them in your .env and restart the server — see README.md §2.'
  );
} else {
  try {
    sb = supabase.createClient(window.APP_CONFIG.SUPABASE_URL, window.APP_CONFIG.SUPABASE_ANON_KEY);
  } catch (err) {
    showConfigError(`Configuration error: could not create the Supabase client (${err.message}). Is SUPABASE_URL a valid URL?`);
  }
}
