// One Supabase client per page load, shared by every other script on the
// page (guard.js, api-client.js, and the page-specific script). Must be
// loaded after config.js (defines window.APP_CONFIG) and the Supabase CDN
// script, before anything that references `sb`.
const sb = supabase.createClient(window.APP_CONFIG.SUPABASE_URL, window.APP_CONFIG.SUPABASE_ANON_KEY);
