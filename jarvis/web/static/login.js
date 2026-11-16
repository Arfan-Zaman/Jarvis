'use strict';
const form = document.getElementById('form');
const error = document.getElementById('error');
form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = form.querySelector('button');
  button.disabled = true;
  error.textContent = '';
  try {
    const response = await fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code: document.getElementById('code').value }),
    });
    if (response.ok) { location.replace('/'); return; }
    const data = await response.json().catch(() => ({}));
    error.textContent = data.error || 'Could not sign in.';
  } catch (e) {
    error.textContent = 'Could not reach JARVIS. Is your Mac awake and online?';
  }
  button.disabled = false;
});
