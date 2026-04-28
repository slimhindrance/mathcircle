// Math Circle Home — session interactivity
// Hint reveal, answer check (informal), parent rating, attempt persistence.

(function () {
  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.from((root || document).querySelectorAll(sel)); }

  const cards = $$('.problem[data-problem-id]');
  const total = cards.length;
  const childId = window.MC_CHILD_ID;
  const sessionId = window.MC_SESSION_ID;
  const startedTimes = new Map();

  let attemptedDone = 0;

  function bumpProgress() {
    const bar = $('.session-bar .progress > i');
    if (!bar) return;
    const ratio = total ? (attemptedDone / total) : 0;
    bar.style.width = (ratio * 100).toFixed(0) + '%';
  }

  cards.forEach(card => {
    const pid = card.dataset.problemId;
    startedTimes.set(pid, Date.now());

    // Hint reveal
    const hintsBox = $('.hints', card);
    const hintBtn = $('.btn-hint', card);
    if (hintBtn && hintsBox) {
      hintBtn.addEventListener('click', () => {
        const locked = $$('.hint.locked', hintsBox);
        if (locked.length === 0) {
          hintBtn.disabled = true;
          hintBtn.textContent = 'No more hints';
          return;
        }
        const next = locked[0];
        next.classList.remove('locked');
        next.classList.add('shown');
        const remaining = locked.length - 1;
        hintBtn.textContent = remaining > 0
          ? `Need a hint? (${remaining} more)`
          : 'No more hints';
        if (remaining === 0) hintBtn.disabled = true;
      });
    }

    // Answer check (informal — just compares text/numeric, lenient)
    const checkBtn = $('.btn-check', card);
    const ansInput = $('.answer-input', card);
    const fb = $('.feedback', card);
    const expected = (card.dataset.answer || '').trim();
    const ansType = card.dataset.answerType || 'open';

    if (checkBtn && ansInput) {
      checkBtn.addEventListener('click', () => {
        const given = (ansInput.value || '').trim();
        let isCorrect = null;
        if (!expected || ansType === 'open' || ansType === 'set') {
          isCorrect = null;
          fb.textContent = '✏️  Talk it through with your grown-up!';
          fb.className = 'feedback';
        } else if (ansType === 'number') {
          const a = parseFloat(given.replace(/[^\-0-9.]/g, ''));
          const b = parseFloat(expected.replace(/[^\-0-9.]/g, ''));
          isCorrect = !isNaN(a) && !isNaN(b) && a === b;
          fb.textContent = isCorrect ? '✓ Yes!' : '🤔 Try again or grab a hint';
          fb.className = isCorrect ? 'feedback correct' : 'feedback wrong';
        } else {
          isCorrect = given.toLowerCase() === expected.toLowerCase();
          fb.textContent = isCorrect ? '✓ Yes!' : '🤔 Talk it through';
          fb.className = isCorrect ? 'feedback correct' : 'feedback wrong';
        }
        // record attempt
        const t = Math.round((Date.now() - startedTimes.get(pid)) / 1000);
        const hintCount = $$('.hint.shown', card).length;
        const strategyNote = ($('.strategy-input', card)?.value || '').trim();
        sendAttempt({
          problem_id: parseInt(pid, 10),
          session_id: sessionId,
          answer_given: given,
          correct: isCorrect,
          hint_count: hintCount,
          strategy_note: strategyNote,
          time_seconds: t,
          parent_rating: card.dataset.parentRating || null,
        });
        if (!card.dataset.recorded) {
          card.dataset.recorded = '1';
          attemptedDone += 1;
          bumpProgress();
        }
      });
    }

    // Parent rating chips
    const ratingBtns = $$('.rating-row button', card);
    ratingBtns.forEach(btn => {
      btn.addEventListener('click', () => {
        ratingBtns.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        card.dataset.parentRating = btn.dataset.value;
        // record / update
        const t = Math.round((Date.now() - startedTimes.get(pid)) / 1000);
        const hintCount = $$('.hint.shown', card).length;
        const strategyNote = ($('.strategy-input', card)?.value || '').trim();
        const ansVal = ($('.answer-input', card)?.value || '').trim();
        sendAttempt({
          problem_id: parseInt(pid, 10),
          session_id: sessionId,
          answer_given: ansVal,
          correct: card.dataset.lastCorrect === 'true' ? true : (card.dataset.lastCorrect === 'false' ? false : null),
          hint_count: hintCount,
          strategy_note: strategyNote,
          time_seconds: t,
          parent_rating: btn.dataset.value,
        });
        if (!card.dataset.recorded) {
          card.dataset.recorded = '1';
          attemptedDone += 1;
          bumpProgress();
        }
      });
    });
  });

  function sendAttempt(payload) {
    if (!childId) return;
    fetch(`/api/children/${childId}/attempts`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    }).catch(() => {});
  }

  // Complete session button
  const completeBtn = $('#complete-session');
  if (completeBtn) {
    completeBtn.addEventListener('click', () => {
      const summaryEl = $('#parent-summary');
      const summary = summaryEl ? summaryEl.value : '';
      fetch(`/api/sessions/${sessionId}/complete`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({summary}),
      }).then(r => {
        if (r.ok) window.location.href = `/child/${childId}`;
      });
    });
  }

  bumpProgress();
})();
