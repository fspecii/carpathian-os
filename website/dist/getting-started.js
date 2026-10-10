'use strict';
const copyButton = document.querySelector('#copy-checksum');
const copyStatus = document.querySelector('#copy-status');
copyButton.addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(document.querySelector('#published-checksum').textContent.trim());
    copyStatus.textContent = 'Checksum copied.';
  } catch {
    copyStatus.textContent = 'Select the checksum above to copy it manually.';
  }
});
