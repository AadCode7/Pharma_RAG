// If there's already a live session, skip the login page entirely.
(async function redirectIfSignedIn() {
  const { data } = await sb.auth.getSession();
  if (data.session) window.location.replace('/');
})();

document.getElementById('btn-google').addEventListener('click', () => {
  sb.auth.signInWithOAuth({ provider: 'google', options: { redirectTo: `${window.location.origin}/` } });
});

// --- Sign in <-> create account toggle ---

let authMode = 'signin';

const authForm = document.getElementById('auth-form');
const authHeading = document.getElementById('auth-heading');
const authSubtitle = document.getElementById('auth-subtitle');
const authSubmit = document.getElementById('auth-submit');
const authToggleBtn = document.getElementById('auth-toggle-btn');
const authToggleText = document.getElementById('auth-toggle-text');
const fullnameGroup = document.getElementById('fullname-group');
const authStatus = document.getElementById('auth-status');
const authPasswordInput = document.getElementById('auth-password');

function setAuthMode(mode) {
  authMode = mode;
  authStatus.hidden = true;

  if (mode === 'signup') {
    authHeading.textContent = 'Create your account';
    authSubtitle.textContent = 'Get started with your work email.';
    authSubmit.textContent = 'Create Account';
    fullnameGroup.hidden = false;
    authPasswordInput.setAttribute('autocomplete', 'new-password');
    authToggleText.textContent = 'Already have an account?';
    authToggleBtn.textContent = 'Sign in';
  } else {
    authHeading.textContent = 'Sign in';
    authSubtitle.textContent = 'Use your email and password.';
    authSubmit.textContent = 'Sign In';
    fullnameGroup.hidden = true;
    authPasswordInput.setAttribute('autocomplete', 'current-password');
    authToggleText.textContent = "Don't have an account?";
    authToggleBtn.textContent = 'Create one';
  }
}

authToggleBtn.addEventListener('click', () => setAuthMode(authMode === 'signin' ? 'signup' : 'signin'));

authForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const email = document.getElementById('auth-email').value.trim();
  const password = authPasswordInput.value;
  const fullName = document.getElementById('auth-fullname').value.trim();

  authSubmit.disabled = true;
  authSubmit.textContent = authMode === 'signup' ? 'Creating…' : 'Signing in…';
  authStatus.hidden = true;

  try {
    if (authMode === 'signup') {
      const { data, error } = await sb.auth.signUp({
        email,
        password,
        options: { data: { full_name: fullName } },
      });
      if (error) throw error;

      if (data.session) {
        // Email confirmation is off for this project — session issued immediately.
        window.location.href = '/';
        return;
      }
      // Email confirmation is on — no session yet, tell them to check their inbox.
      authStatus.hidden = false;
      authStatus.className = 'auth-status';
      authStatus.textContent = `Check ${email} to confirm your account, then sign in.`;
      setAuthMode('signin');
    } else {
      const { error } = await sb.auth.signInWithPassword({ email, password });
      if (error) throw error;
      window.location.href = '/';
      return;
    }
  } catch (err) {
    // Full error object to the console — err.message alone (what was shown
    // before) is often just "Failed to fetch", which tells you nothing.
    // Nothing about this call goes through our backend, so this console
    // log is the only place the real cause shows up — check it here, not
    // the server terminal.
    console.error(`[Pharma RAG] ${authMode} failed:`, err);
    authStatus.hidden = false;
    authStatus.className = 'auth-status is-error';
    authStatus.textContent = describeAuthError(err);
  } finally {
    authSubmit.disabled = false;
    authSubmit.textContent = authMode === 'signup' ? 'Create Account' : 'Sign In';
  }
});

function describeAuthError(err) {
  // The Fetch API throws a plain TypeError with exactly this message when
  // the request never reaches a server at all — DNS failure, connection
  // refused, CORS block, offline. That's a config/network problem, not a
  // rejected sign-in, so it gets a different, more actionable message.
  if (err instanceof TypeError && /fetch/i.test(err.message)) {
    return "Couldn't reach the authentication server. Check your internet connection and open the browser console for details — SUPABASE_URL in your .env is the most common cause.";
  }
  return err.message || 'Something went wrong. Check the browser console for details.';
}
