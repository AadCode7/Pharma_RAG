// Handle Supabase email-confirmation redirects before applying the normal
// signed-in redirect. Supabase may return auth tokens in the URL hash after
// confirming the address; the client consumes those tokens during initialization.
const authStatus = document.getElementById('auth-status');

(async function initializeLoginPage() {
  const params = new URLSearchParams(window.location.search);
  const emailConfirmed = params.get('email_confirmed') === '1';
  const authError = params.get('error_description') || params.get('error');

  if (emailConfirmed) {
    // A confirmation link can establish a session automatically. This app's
    // requested flow is confirmation -> login, so clear only this local session
    // and require the user to sign in with their credentials.
    const { data } = await sb.auth.getSession();
    if (data.session) {
      const { error } = await sb.auth.signOut({ scope: 'local' });
      if (error) console.warn('[Pharma RAG] Could not clear confirmation session:', error);
    }

    window.history.replaceState({}, document.title, '/login');
    authStatus.hidden = false;
    authStatus.className = 'auth-status';
    authStatus.textContent = 'Email confirmed successfully. You can now sign in.';
    return;
  }

  if (authError) {
    window.history.replaceState({}, document.title, '/login');
    authStatus.hidden = false;
    authStatus.className = 'auth-status is-error';
    authStatus.textContent = 'We could not confirm your email. The link may have expired or already been used. Request a new confirmation email or try signing in.';
    return;
  }

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
        options: {
          data: { full_name: fullName },
          // Supabase verifies the token first, then returns the browser to this
          // app's login page. Add this URL to Supabase Auth's allowed redirects.
          emailRedirectTo: `${window.location.origin}/login?email_confirmed=1`,
        },
      });
      if (error) throw error;

      if (data.session) {
        // Email confirmation is disabled in the Supabase project.
        window.location.href = '/';
        return;
      }

      authStatus.hidden = false;
      authStatus.className = 'auth-status';
      authStatus.textContent = `Check ${email} for a confirmation link. After confirming your email, you'll return here to sign in.`;
      setAuthMode('signin');
      // setAuthMode hides the status message, so restore the sign-up guidance.
      authStatus.hidden = false;
      authStatus.className = 'auth-status';
      authStatus.textContent = `Check ${email} for a confirmation link. After confirming your email, you'll return here to sign in.`;
    } else {
      const { error } = await sb.auth.signInWithPassword({ email, password });
      if (error) throw error;
      window.location.href = '/';
      return;
    }
  } catch (err) {
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
  if (err instanceof TypeError && /fetch/i.test(err.message)) {
    return "Couldn't reach the authentication server. Check your internet connection and open the browser console for details — SUPABASE_URL in your .env is the most common cause.";
  }
  return err.message || 'Something went wrong. Check the browser console for details.';
}
