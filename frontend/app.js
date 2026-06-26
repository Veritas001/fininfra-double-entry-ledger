const state = {
  summary: null,
  accounts: [],
  journalEntries: [],
  trialBalance: null,
};

const ids = {
  serviceStatus: document.querySelector("#serviceStatus"),
  dbStatus: document.querySelector("#dbStatus"),
  accountCount: document.querySelector("#accountCount"),
  journalEntryCount: document.querySelector("#journalEntryCount"),
  totalDebits: document.querySelector("#totalDebits"),
  totalCredits: document.querySelector("#totalCredits"),
  difference: document.querySelector("#difference"),
  balancedFlag: document.querySelector("#balancedFlag"),
  invariantHeadline: document.querySelector("#invariantHeadline"),
  invariantDetail: document.querySelector("#invariantDetail"),
  invariantPanel: document.querySelector(".invariant-panel"),
  lastAction: document.querySelector("#lastAction"),
  accountsTable: document.querySelector("#accountsTable"),
  journalEntriesTable: document.querySelector("#journalEntriesTable"),
  trialBalanceTable: document.querySelector("#trialBalanceTable"),
  trialDebitTotal: document.querySelector("#trialDebitTotal"),
  trialCreditTotal: document.querySelector("#trialCreditTotal"),
  refreshButton: document.querySelector("#refreshButton"),
  resetButton: document.querySelector("#resetButton"),
  replayButton: document.querySelector("#replayButton"),
};

function formatNumber(value) {
  return Number(value || 0).toLocaleString("en-US");
}

function formatUsdDifference(value) {
  return `${(Number(value || 0) / 100).toFixed(2)} USD`;
}

async function fetchJson(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const body = await response.json();
  if (!response.ok) {
    throw new Error(body.message || `${path} returned HTTP ${response.status}`);
  }
  return body;
}

async function refreshData(message = "Refreshed ledger state.") {
  ids.lastAction.textContent = "Loading ledger state...";
  const [health, ready, summary, accounts, journalEntries, trialBalance] = await Promise.all([
    fetchJson("/health"),
    fetchJson("/ready"),
    fetchJson("/api/v1/ledger/summary"),
    fetchJson("/api/v1/ledger/accounts"),
    fetchJson("/api/v1/ledger/journal-entries"),
    fetchJson("/api/v1/ledger/trial-balance"),
  ]);

  state.summary = summary;
  state.accounts = accounts.accounts;
  state.journalEntries = journalEntries.journal_entries;
  state.trialBalance = trialBalance;

  renderStatus(health, ready, summary);
  renderAccounts(state.accounts);
  renderJournalEntries(state.journalEntries);
  renderTrialBalance(trialBalance);
  ids.lastAction.textContent = message;
}

function renderStatus(health, ready, summary) {
  ids.serviceStatus.textContent = health.status.toUpperCase();
  ids.dbStatus.textContent = ready.status === "ready" ? "READY" : "NOT READY";
  ids.accountCount.textContent = formatNumber(summary.account_count);
  ids.journalEntryCount.textContent = formatNumber(summary.journal_entry_count);
  ids.totalDebits.textContent = formatNumber(summary.total_debits);
  ids.totalCredits.textContent = formatNumber(summary.total_credits);
  ids.difference.textContent = formatNumber(summary.trial_balance_difference);
  ids.balancedFlag.textContent = summary.ledger_balanced ? "TRUE" : "FALSE";
  ids.invariantHeadline.textContent = `Ledger Balanced: ${summary.ledger_balanced ? "TRUE" : "FALSE"}`;
  ids.invariantDetail.textContent = summary.ledger_balanced
    ? `Total Debits = Total Credits. Difference = ${formatUsdDifference(summary.trial_balance_difference)}. Total Debits = ${summary.total_debits}. Total Credits = ${summary.total_credits}.`
    : `Total Debits do not equal Total Credits. Difference = ${formatUsdDifference(summary.trial_balance_difference)}.`;
  ids.invariantPanel.classList.toggle("ok", summary.ledger_balanced);
  ids.invariantPanel.classList.toggle("bad", !summary.ledger_balanced);
}

function renderAccounts(accounts) {
  if (!accounts.length) {
    ids.accountsTable.innerHTML = `<tr><td colspan="7">No accounts yet. Replay Settlement Demo to seed the local ledger.</td></tr>`;
    return;
  }

  ids.accountsTable.innerHTML = accounts
    .map(
      (account) => `
        <tr>
          <td><strong>${escapeHtml(account.code)}</strong></td>
          <td>${escapeHtml(account.name)}</td>
          <td><span class="pill">${escapeHtml(account.account_type)}</span></td>
          <td>${escapeHtml(account.normal_side)}</td>
          <td class="numeric">${formatNumber(account.debit_total)}</td>
          <td class="numeric">${formatNumber(account.credit_total)}</td>
          <td class="numeric">${escapeHtml(account.display_balance)}</td>
        </tr>
      `,
    )
    .join("");
}

function renderJournalEntries(entries) {
  if (!entries.length) {
    ids.journalEntriesTable.innerHTML = `<tr><td colspan="5">No journal entries yet. Replay Settlement Demo to post the deterministic flow.</td></tr>`;
    return;
  }

  ids.journalEntriesTable.innerHTML = entries
    .map(
      (entry) => `
        <tr>
          <td><strong>${escapeHtml(entry.external_reference || entry.journal_entry_id)}</strong></td>
          <td>${escapeHtml(entry.description || "")}</td>
          <td><span class="pill">${escapeHtml(entry.status)}</span></td>
          <td>${escapeHtml(entry.posted_at || entry.created_at || "")}</td>
          <td>
            <ul class="posting-list">
              ${entry.postings
                .map(
                  (posting) => `
                    <li>${escapeHtml(posting.account)}: Dr ${formatNumber(posting.debit_amount)} / Cr ${formatNumber(posting.credit_amount)} ${escapeHtml(posting.currency)}</li>
                  `,
                )
                .join("")}
            </ul>
          </td>
        </tr>
      `,
    )
    .join("");
}

function renderTrialBalance(trialBalance) {
  if (!trialBalance.rows.length) {
    ids.trialBalanceTable.innerHTML = `<tr><td colspan="4">No trial balance rows yet.</td></tr>`;
    ids.trialDebitTotal.textContent = "0";
    ids.trialCreditTotal.textContent = "0";
    return;
  }

  ids.trialBalanceTable.innerHTML = trialBalance.rows
    .map(
      (row) => `
        <tr>
          <td><strong>${escapeHtml(row.code)}</strong> ${escapeHtml(row.name)}</td>
          <td>${escapeHtml(row.account_type)}</td>
          <td class="numeric">${formatNumber(row.trial_debit_balance)}</td>
          <td class="numeric">${formatNumber(row.trial_credit_balance)}</td>
        </tr>
      `,
    )
    .join("");
  ids.trialDebitTotal.textContent = formatNumber(trialBalance.total_debits);
  ids.trialCreditTotal.textContent = formatNumber(trialBalance.total_credits);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function runAction(action, successMessage) {
  try {
    setButtonsDisabled(true);
    ids.lastAction.textContent = `${successMessage}...`;
    await action();
    await refreshData(successMessage);
  } catch (error) {
    ids.lastAction.textContent = `Error: ${error.message}`;
  } finally {
    setButtonsDisabled(false);
  }
}

function setButtonsDisabled(disabled) {
  ids.refreshButton.disabled = disabled;
  ids.resetButton.disabled = disabled;
  ids.replayButton.disabled = disabled;
}

ids.refreshButton.addEventListener("click", () => runAction(() => Promise.resolve(), "Refreshed ledger state."));
ids.resetButton.addEventListener("click", () =>
  runAction(() => fetchJson("/api/v1/ledger/demo/reset", { method: "POST" }), "Reset demo ledger."),
);
ids.replayButton.addEventListener("click", () =>
  runAction(
    () => fetchJson("/api/v1/ledger/demo/replay-settlement", { method: "POST" }),
    "Replayed settlement demo.",
  ),
);

refreshData("Loaded ledger control room.").catch((error) => {
  ids.lastAction.textContent = `Error: ${error.message}`;
});
