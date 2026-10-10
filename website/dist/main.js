'use strict';
// Set only after the curated repository is public. No placeholder external URL.
const config = { githubUrl: null };
const toggle = document.querySelector('.menu-toggle');
const navigation = document.querySelector('#navigation');
function closeMenu() { navigation.removeAttribute('data-open'); toggle.setAttribute('aria-expanded', 'false'); }
toggle.addEventListener('click', () => { const open = toggle.getAttribute('aria-expanded') !== 'true'; toggle.setAttribute('aria-expanded', String(open)); navigation.toggleAttribute('data-open', open); });
navigation.addEventListener('click', event => { if (event.target.closest('a')) closeMenu(); });
document.addEventListener('keydown', event => { if (event.key === 'Escape' && toggle.getAttribute('aria-expanded') === 'true') { closeMenu(); toggle.focus(); } });
window.matchMedia('(min-width: 661px)').addEventListener('change', event => { if (event.matches) closeMenu(); });
if (config.githubUrl && /^https:\/\/github\.com\//.test(config.githubUrl)) { const link = document.querySelector('#source-link'); link.href = config.githubUrl; link.hidden = false; }
