/* chatbot.js — Provenance AI Assistant (fully offline, vanilla JS)
   Pre-programmed Q&A covering all features. No external API calls.
   MOCKED: production would use a real LLM backend.
*/

(function () {
  "use strict";

  // ── Knowledge base ─────────────────────────────────────────
  const KB = [
    {
      keys: ["what is provenance", "what is this", "about", "overview", "explain"],
      answer:
        "**Provenance** is an AI-governed research collaboration platform. It combines a tamper-evident ledger, AI scoping/matching agents, a workspace agent with an injection firewall, and a smart escrow system — all designed to make academic research transparent, fair, and accountable.<br><br>Think of it as: <em>GitHub × Academic Publishing × AI Governance</em>."
    },
    {
      keys: ["ledger", "blockchain", "hash", "chain", "tamper", "chain verified", "integrity"],
      answer:
        "Every action in Provenance — contribution, review, payment, AI call — is SHA-256 hashed into an append-only chain. If anyone modifies a past entry, the chain breaks instantly.<br><br>You can inspect it live at <a href='/ledger'>/ledger</a>. Look for <strong style='color:#C6FF3D'>CHAIN VERIFIED</strong>."
    },
    {
      keys: ["credits", "credit", "score", "points", "contribution score", "leaderboard", "ranking"],
      answer:
        "The <strong>Contribution Credit</strong> formula rewards verified work:<br><br>• 📝 Contribution submitted → <strong>20 cr</strong><br>• ✅ Contribution reviewed → <strong>30 cr</strong><br>• 🏆 Milestone accepted → <strong>50 cr</strong><br>• 🤖 AI action approved → <strong>15 cr</strong><br>• 📜 Charter signed → <strong>5 cr</strong><br><br>Credits are computed on-chain — you can't game them without breaking the ledger."
    },
    {
      keys: ["ai scoping", "scoping agent", "milestones proposed", "propose milestones"],
      answer:
        "The <strong>AI Scoping Agent</strong> reads the confidential brief (after redacting PII) and proposes structured milestones with titles, deliverables, acceptance criteria, and required skills.<br><br>⚠ It can <em>never</em> auto-apply milestones — the sponsor must approve each one before work begins. Try it at <a href='/projects/7/scoping'>/projects/7/scoping</a>."
    },
    {
      keys: ["matching", "team matching", "candidates", "recommend", "arvind", "who is recommended"],
      answer:
        "The <strong>AI Matching Engine</strong> scores every researcher on:<br>• Skill overlap with required skills<br>• Verification level<br>• Newcomer boost (first project)<br>• Conflict-of-interest rules<br><br><strong>Arvind Nair</strong> is the recommended expert. <strong>Kiran Shah</strong> is auto-excluded because his institution (MedVision Labs) conflicts with the sponsor. See it at <a href='/projects/7/matching'>/projects/7/matching</a>."
    },
    {
      keys: ["workspace agent", "draft", "agent draft", "workspace"],
      answer:
        "Project members can ask the <strong>Workspace Agent</strong> to draft content from a source document. The agent returns a draft marked <em>PENDING</em>.<br><br>The human owner must review and approve the draft before it becomes a contribution — no AI output is ever auto-submitted. Try at <a href='/projects/10/workspace'>/projects/10/workspace</a>."
    },
    {
      keys: ["firewall", "injection", "prompt injection", "blocked", "hostile", "send_email", "attacker"],
      answer:
        "The <strong>AI Firewall</strong> scans every source document for prompt-injection attacks. If it finds lines like <code>IGNORE ALL PREVIOUS INSTRUCTIONS</code>, it:<br>1. Flags the call with labels (e.g. <em>ignore_instructions</em>)<br>2. Strips all TOOL: lines from the output<br>3. Requires the owner to confirm they reviewed the flagged document before approving<br><br>Try loading the sample injection document on the <a href='/projects/10/workspace'>Workspace</a> page."
    },
    {
      keys: ["escrow", "payment", "money", "inr", "payout", "fund", "funded"],
      answer:
        "Funds are locked in <strong>escrow</strong> at milestone creation and only released after:<br>1. Expert reviews and approves contributions<br>2. Sponsor accepts the milestone<br><br>A deterministic <strong>split engine</strong> distributes INR amounts conserved to the last rupee. Every payout is on the ledger with a verifiable receipt."
    },
    {
      keys: ["credentials", "badge", "certificate", "verify", "proof"],
      answer:
        "On milestone acceptance, every contributor receives a <strong>64-hex credential hash</strong> tied to their contribution hash. Credentials are independently verifiable — no institution can revoke them. Check at <a href='/credentials'>/credentials</a>."
    },
    {
      keys: ["charter", "rules", "join", "membership", "how to join"],
      answer:
        "Every project has a <strong>Charter</strong> — its constitution. Members must accept the current charter version. If the sponsor updates it, members must re-accept before continuing work.<br><br>Joining: Go to a project → click Join → accept the charter. Students and Experts can join open projects."
    },
    {
      keys: ["meera", "sponsor", "who is meera"],
      answer:
        "👩‍💼 <strong>Meera Rao</strong> is the demo <em>Sponsor</em> from MedVision Labs. She posts research projects, approves milestones, and reviews AI-generated team recommendations. <a href='/switch/2'>Switch to Meera →</a>"
    },
    {
      keys: ["arvind", "expert", "who is arvind"],
      answer:
        "🔬 <strong>Arvind Nair</strong> is the recommended <em>Expert</em> (verification level 3). He reviews contributions, submits milestones for acceptance, and earns the highest credits. <a href='/switch/3'>Switch to Arvind →</a>"
    },
    {
      keys: ["ananya", "student", "who is ananya"],
      answer:
        "🎓 <strong>Ananya</strong> is a student member who can submit contributions (including AI-assisted drafts) and earn contribution credits. <a href='/switch/5'>Switch to Ananya →</a>"
    },
    {
      keys: ["kiran", "conflict", "excluded", "conflict of interest"],
      answer:
        "⚠ <strong>Kiran Shah</strong> is automatically <em>excluded</em> from the matching result because his institution conflicts with the sponsor (MedVision Labs). This is enforced by the matching engine — no human had to manually flag it."
    },
    {
      keys: ["tara", "minor", "guardian"],
      answer:
        "👧 <strong>Tara</strong> is a <em>minor</em> student. The system requires guardian consent for minors and shows a special chip on her profile. The matching engine flags her guardian requirement in excluded results."
    },
    {
      keys: ["admin", "asha", "who is admin"],
      answer:
        "🛡 <strong>Admin Asha</strong> has cross-project visibility — she can see all projects, all ledger entries, and manage the system. <a href='/switch/1'>Switch to Admin →</a>"
    },
    {
      keys: ["how does it work", "demo", "walkthrough", "guide", "start", "where to begin"],
      answer:
        "Here's the fastest demo path for judges:<br><br>1. <a href='/switch/2'>Switch to Meera Rao (Sponsor)</a><br>2. <a href='/projects/7/scoping'>AI Scoping</a> → propose milestones<br>3. <a href='/projects/7/matching'>AI Matching</a> → see Arvind ranked, Kiran excluded<br>4. <a href='/switch/5'>Switch to Ananya (Student)</a><br>5. <a href='/projects/10/workspace'>Workspace Agent</a> → draft + injection test<br>6. <a href='/ledger'>Ledger</a> → see chain + contribution credits<br>7. <a href='/credentials'>Credentials</a> → verify badges"
    },
    {
      keys: ["unique", "different", "what makes", "special", "innovation"],
      answer:
        "6 interlocking innovations no existing platform combines:<br><br>⛓ Tamper-evident SHA-256 ledger<br>🤖 AI Scoping (human-approved)<br>⚡ Fairness-aware team matching<br>🛡 Prompt-injection AI firewall<br>💰 Smart escrow + split engine<br>🏅 Self-sovereign credential hashes"
    },
    {
      keys: ["sensitivity", "confidential", "public", "internal", "visibility"],
      answer:
        "Projects have 3 sensitivity levels:<br>• <strong>PUBLIC</strong> — anyone can read the summary<br>• <strong>INTERNAL</strong> — only members see details<br>• <strong>CONFIDENTIAL</strong> — AI never sends data to external APIs; uses local/canned model only<br><br>The AI Firewall enforces this automatically."
    },
    {
      keys: ["route", "api", "local", "canned", "model", "ollama", "gemini"],
      answer:
        "The AI Gateway routes calls based on sensitivity:<br>• Confidential → local Ollama model (or canned MOCKED fallback)<br>• Internal + API key → Gemini API<br>• No key → canned MOCKED response<br><br>The Firewall page shows the actual route used for every call. In this demo: <strong>canned (MOCKED)</strong>."
    },
    {
      keys: ["hello", "hi", "hey", "good morning", "good afternoon"],
      answer:
        "Hi! 👋 I'm the <strong>Provenance AI Assistant</strong>. I can explain any feature of the platform.<br><br>Try asking me: <em>"How does the ledger work?"</em>, <em>"What makes this unique?"</em>, or <em>"Show me the demo path."</em>"
    },
  ];

  // ── Suggested quick replies ──────────────────────────────────
  const QUICK_REPLIES = [
    "What makes this unique?",
    "How do credits work?",
    "Show me the demo path",
    "What is the AI Firewall?",
    "How does scoping work?",
    "Who is Kiran Shah?",
  ];

  // ── DOM ────────────────────────────────────────────────────
  let panelOpen = false;
  let panel, messages, inputEl;

  function createUI() {
    // FAB button
    const fab = document.createElement("button");
    fab.className = "chatbot-fab";
    fab.id = "chatbot-fab";
    fab.title = "Chat with Provenance AI";
    fab.innerHTML = "✦<div class='fab-badge'></div>";
    fab.addEventListener("click", togglePanel);
    document.body.appendChild(fab);

    // Panel
    panel = document.createElement("div");
    panel.className = "chatbot-panel hidden";
    panel.id = "chatbot-panel";
    panel.innerHTML = `
      <div class="chatbot-header">
        <div class="chatbot-avatar">✦</div>
        <div>
          <div class="chatbot-title">Provenance AI</div>
          <div class="chatbot-status">● Online · MOCKED</div>
        </div>
        <button class="chatbot-close" title="Close" onclick="document.getElementById('chatbot-panel').classList.add('hidden');document.querySelector('.chatbot-fab').style.animation=''">✕</button>
      </div>
      <div class="chatbot-messages" id="chatbot-messages"></div>
      <div class="chatbot-chips" id="chatbot-chips"></div>
      <div class="chatbot-input-row">
        <input class="chatbot-input" id="chatbot-input" type="text" placeholder="Ask about any feature…" autocomplete="off">
        <button class="chatbot-send" id="chatbot-send">↑</button>
      </div>
    `;
    document.body.appendChild(panel);

    messages = document.getElementById("chatbot-messages");
    inputEl = document.getElementById("chatbot-input");

    document.getElementById("chatbot-send").addEventListener("click", sendMsg);
    inputEl.addEventListener("keydown", function (e) {
      if (e.key === "Enter") sendMsg();
    });

    // Quick replies
    const chipsEl = document.getElementById("chatbot-chips");
    QUICK_REPLIES.forEach(function (q) {
      const chip = document.createElement("button");
      chip.className = "chatbot-chip";
      chip.textContent = q;
      chip.addEventListener("click", function () {
        inputEl.value = q;
        sendMsg();
      });
      chipsEl.appendChild(chip);
    });

    // Welcome message
    setTimeout(function () {
      addBotMsg(
        "Hi! 👋 I'm the <strong>Provenance AI Assistant</strong>.<br>" +
        "Ask me anything about the platform — ledger, AI agents, credits, matching, firewall…<br>" +
        "<em>MOCKED: pre-programmed responses for the demo.</em>"
      );
    }, 400);
  }

  function togglePanel() {
    panelOpen = !panelOpen;
    panel.classList.toggle("hidden", !panelOpen);
    if (panelOpen) messages.scrollTop = messages.scrollHeight;
  }

  function addBotMsg(html) {
    const row = document.createElement("div");
    row.className = "msg msg-bot";
    row.innerHTML = `<div class="msg-avatar msg-avatar-bot">✦</div><div class="msg-bubble msg-bubble-bot">${html}</div>`;
    messages.appendChild(row);
    messages.scrollTop = messages.scrollHeight;
  }

  function addUserMsg(text) {
    const row = document.createElement("div");
    row.className = "msg msg-user";
    row.innerHTML = `<div class="msg-avatar msg-avatar-user">👤</div><div class="msg-bubble msg-bubble-user">${escHtml(text)}</div>`;
    messages.appendChild(row);
    messages.scrollTop = messages.scrollHeight;
  }

  function showTyping() {
    const row = document.createElement("div");
    row.className = "msg msg-bot";
    row.id = "typing-indicator";
    row.innerHTML = `<div class="msg-avatar msg-avatar-bot">✦</div><div class="msg-bubble msg-bubble-bot"><div class="typing-indicator"><div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div></div></div>`;
    messages.appendChild(row);
    messages.scrollTop = messages.scrollHeight;
  }

  function removeTyping() {
    const t = document.getElementById("typing-indicator");
    if (t) t.remove();
  }

  function sendMsg() {
    const raw = inputEl.value.trim();
    if (!raw) return;
    inputEl.value = "";
    addUserMsg(raw);
    showTyping();
    setTimeout(function () {
      removeTyping();
      const reply = findAnswer(raw.toLowerCase());
      addBotMsg(reply);
    }, 600 + Math.random() * 400);
  }

  function findAnswer(q) {
    for (var i = 0; i < KB.length; i++) {
      var entry = KB[i];
      for (var j = 0; j < entry.keys.length; j++) {
        if (q.indexOf(entry.keys[j]) !== -1) return entry.answer;
      }
    }
    return (
      "I don't have a specific answer for that, but here are some things you can explore:<br><br>" +
      "• <a href='/ledger'>Ledger & Credits</a><br>" +
      "• <a href='/projects'>Projects</a><br>" +
      "• <a href='/credentials'>Credentials</a><br><br>" +
      "Or try asking: <em>\"What makes this unique?\"</em> or <em>\"Show me the demo path.\"</em>"
    );
  }

  function escHtml(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // ── Init ──────────────────────────────────────────────────────
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", createUI);
  } else {
    createUI();
  }
})();
