// Runs on every authenticated page (included via base.html). Responsibilities:
//   1. Confirm there's a live session; redirect to /login immediately if not.
//   2. Populate the sidebar (name, role, admin link visibility).
//   3. Wire up sign-out so it actually revokes the session, not just
//      forgets it client-side.
//   4. Keep watching auth state for the rest of the page's life — if the
//      session is revoked or expires while the tab is open, redirect then too.
//
// Page-specific scripts (query.js, trace.js, ...) should not fetch data
// until the 'auth-ready' event fires, since that's the point at which the
// session is confirmed valid and window.currentUserId/currentUserRole are set.

(async function guard() {
  try {
    const { data, error } = await sb.auth.getSession();

    if (error || !data.session) {
      window.location.replace('/login');
      return;
    }

    await populateSidebar(data.session);
    document.body.hidden = false;
  } catch (err) {
    // Whatever went wrong, the page must not stay permanently blank
    // (body starts `hidden`) with nothing explaining why. Surface it.
    console.error('[Pharma RAG] Session check failed:', err);
    document.body.hidden = false;
    const banner = document.createElement('div');
    banner.textContent = 'Something went wrong checking your session. Check the browser console, then try refreshing.';
    banner.style.cssText =
      'position:fixed;top:0;left:0;right:0;z-index:9999;background:#D70015;color:#fff;' +
      'padding:0.75rem 1rem;font:14px -apple-system,BlinkMacSystemFont,sans-serif;text-align:center;';
    document.body.prepend(banner);
  }
})();

async function populateSidebar(session) {
  const { data: profile, error } = await sb
    .from('profiles')
    .select('role, full_name')
    .eq('id', session.user.id)
    .single();

  if (error) {
    // Don't fail silently into "employee" — a missing/unreadable profile
    // row is worth knowing about (e.g. the handle_new_user() trigger from
    // the migration didn't fire, or RLS is misconfigured).
    console.error('[Pharma RAG] Could not load profile — defaulting to employee role:', error);
  }

  const role = profile?.role || 'employee';

  document.getElementById('user-name').textContent = profile?.full_name || session.user.email;
  document.getElementById('user-role').textContent = role;

  const adminLink = document.getElementById('nav-admin');
  if (adminLink) adminLink.hidden = role !== 'manager';

  window.currentUserId = session.user.id;
  window.currentUserRole = role;

  document.dispatchEvent(new CustomEvent('auth-ready', { detail: { userId: session.user.id, role } }));
}

// If the session disappears while this tab is open (expiry, revocation from
// another tab, etc.), bounce to /login rather than leaving a half-authed page up.
sb.auth.onAuthStateChange((_event, session) => {
  if (!session) window.location.replace('/login');
});

document.getElementById('btn-sign-out')?.addEventListener('click', async () => {
  const btn = document.getElementById('btn-sign-out');
  btn.disabled = true;
  btn.textContent = 'Signing out…';

  try {
    // Default scope ('local') clears this device's session and revokes its
    // refresh token server-side — the actual credential is invalidated, not
    // just forgotten in the browser. Use { scope: 'global' } instead if you
    // ever need "sign out of all devices."
    const { error } = await sb.auth.signOut();
    if (error) console.error('[Pharma RAG] Sign out returned an error (proceeding to /login anyway):', error);
  } catch (err) {
    console.error('[Pharma RAG] Sign out threw (proceeding to /login anyway):', err);
  } finally {
    // Redirect regardless of what signOut() did — even a failed server-side
    // revoke shouldn't leave someone stuck on an authenticated page with no
    // way out. Supabase's client also clears its local storage state as
    // part of signOut() before this point, so /login's own session check
    // won't bounce them straight back in.
    window.location.replace('/login');
  }
});
