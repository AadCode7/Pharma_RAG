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
  const { data, error } = await sb.auth.getSession();

  if (error || !data.session) {
    window.location.replace('/login');
    return;
  }

  await populateSidebar(data.session);
  document.body.hidden = false;
})();

async function populateSidebar(session) {
  const { data: profile } = await sb
    .from('profiles')
    .select('role, full_name')
    .eq('id', session.user.id)
    .single();

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

  // Default scope ('local') clears this device's session and revokes its
  // refresh token server-side — the actual credential is invalidated, not
  // just forgotten in the browser. Use { scope: 'global' } instead if you
  // ever need "sign out of all devices."
  await sb.auth.signOut();
  window.location.replace('/login');
});
