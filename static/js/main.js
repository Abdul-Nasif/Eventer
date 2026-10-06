/* ============================================================
   main.js  —  self-contained; everything runs after DOM ready
   ============================================================ */

document.addEventListener("DOMContentLoaded", () => {

  /* --------------------------------------------------
     Tooltip helpers (shared by admin + success page)
     -------------------------------------------------- */
  const tooltipEl = document.getElementById("globalTooltip");

  function showTooltip(target, html) {
    if (!tooltipEl) return;
    tooltipEl.innerHTML = html;
    tooltipEl.classList.add("visible");

    const r = target.getBoundingClientRect();
    const t = tooltipEl.getBoundingClientRect();

    let left = r.left + r.width / 2 - t.width / 2;
    let top  = r.top - t.height - 8;

    left = Math.max(8, Math.min(left, window.innerWidth - t.width - 8));
    if (top < 8) top = r.bottom + 8;

    tooltipEl.style.left = left + "px";
    tooltipEl.style.top  = top  + "px";
  }

  function hideTooltip() {
    if (tooltipEl) tooltipEl.classList.remove("visible");
  }

  window.addEventListener("scroll", hideTooltip, true);
  window.addEventListener("resize", hideTooltip);

  /* --------------------------------------------------
     Copy-to-clipboard (success page)
     -------------------------------------------------- */
  document.querySelectorAll("[data-copy]").forEach((btn) => {
    btn.addEventListener("click", () => {
      navigator.clipboard.writeText(btn.dataset.copy).then(() => {
        const old = btn.textContent;
        btn.textContent = "Copied!";
        setTimeout(() => { btn.textContent = old; }, 1500);
      });
    });
  });

  /* ==================================================
     ADMIN PANEL
     ================================================== */
  const adminRoot = document.getElementById("adminRoot");
  if (!adminRoot) return;   // not on admin page — we're done

  console.log("[admin] panel initialised");

  const tbody        = document.getElementById("adminTbody");
  const searchInput  = document.getElementById("searchFilter");
  const statusSelect = document.getElementById("statusFilter");
  const planSelect   = document.getElementById("planFilter");
  const countLabel   = document.getElementById("countLabel");
  const emptyFilter  = document.getElementById("emptyFilter");
  const expandAllBtn = document.getElementById("expandAllBtn");

  const rows = tbody
    ? Array.from(tbody.querySelectorAll("tr.main-row[data-id]"))
    : [];

  /* -------------------- expand / collapse -------------------- */
  function detailRowFor(id) {
    return tbody?.querySelector('tr.detail-row[data-for="' + id + '"]') || null;
  }

  function setExpanded(mainRow, expanded) {
    const detail = detailRowFor(mainRow.dataset.id);
    if (!detail) return;
    mainRow.dataset.expanded = expanded ? "true" : "false";
    detail.style.display = expanded ? "" : "none";
  }

  function toggleRow(mainRow) {
    setExpanded(mainRow, mainRow.dataset.expanded !== "true");
  }

  /* -------------------- filters -------------------- */
  function applyFilters() {
    const q      = (searchInput?.value || "").toLowerCase().trim();
    const status = statusSelect?.value || "";
    const plan   = planSelect?.value   || "";

    let shown = 0;
    rows.forEach((row) => {
      const haystack = [
        row.dataset.code   || "",
        row.dataset.names  || "",
        row.dataset.emails || "",
        row.dataset.phones || "",
      ].join(" ").toLowerCase();

      const matchesQ      = !q      || haystack.includes(q);
      const matchesStatus = !status || row.dataset.status === status;
      const matchesPlan   = !plan   || row.dataset.plan   === plan;

      const visible = matchesQ && matchesStatus && matchesPlan;
      row.style.display = visible ? "" : "none";

      const detail = detailRowFor(row.dataset.id);
      if (detail) {
        if (!visible) {
          detail.style.display = "none";
          row.dataset.expanded = "false";
        } else {
          detail.style.display = row.dataset.expanded === "true" ? "" : "none";
        }
      }
      if (visible) shown++;
    });

    if (countLabel) {
      countLabel.textContent = shown + " registration" + (shown === 1 ? "" : "s");
    }
    if (emptyFilter) {
      emptyFilter.style.display =
        shown === 0 && rows.length > 0 ? "block" : "none";
    }
  }

  searchInput ?.addEventListener("input",  applyFilters);
  statusSelect?.addEventListener("change", applyFilters);
  planSelect  ?.addEventListener("change", applyFilters);

  /* -------------------- avatar tooltips -------------------- */
  document.querySelectorAll(".avatar").forEach((av) => {
    const html =
      '<p class="t-name">'  + (av.dataset.name  || "") + '</p>' +
      '<p class="t-email">' + (av.dataset.email || "") + '</p>' +
      '<p class="t-email">' + (av.dataset.phone || "") + '</p>' +
      '<p class="t-role">'  + (av.dataset.role  || "") + '</p>';
    av.addEventListener("mouseenter", () => showTooltip(av, html));
    av.addEventListener("mouseleave", hideTooltip);
    av.addEventListener("focus",      () => showTooltip(av, html));
    av.addEventListener("blur",       hideTooltip);
  });

  /* -------------------- screenshot modal -------------------- */
  const modal     = document.getElementById("shotModal");
  const modalImg  = document.getElementById("modalImg");
  const modalCode = document.getElementById("modalCode");

  function openModal(id, code) {
    if (!modal) return;
    if (modalCode) modalCode.textContent = code || "";
    if (modalImg)  modalImg.src = "/admin/screenshot/" + id + "?t=" + Date.now();
    modal.classList.add("open");
  }
  function closeModal() {
    if (!modal) return;
    modal.classList.remove("open");
    if (modalImg) modalImg.src = "";
  }
  document.getElementById("modalClose")?.addEventListener("click", closeModal);
  modal?.addEventListener("click", (e) => { if (e.target === modal) closeModal(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });

  /* -------------------- row status updater -------------------- */
  function setRowStatus(mainRow, status) {
    if (!mainRow) return;
    const badge = mainRow.querySelector(".badge");
    if (badge) {
      badge.className = "badge " + (
        status === "approved"         ? "badge-active"      :
        status === "rejected"         ? "badge-inactive"    :
        status === "pending_approval" ? "badge-in-progress" :
                                        "badge-pending"
      );
      badge.textContent = status.replace(/_/g, " ")
        .replace(/\b\w/g, (c) => c.toUpperCase());
    }
    mainRow.dataset.status = status;

    const locked = ["approved", "rejected", "pending_payment"].includes(status);
    mainRow.querySelectorAll(".approve-btn, .reject-btn").forEach((b) => {
      b.disabled = locked;
      b.style.opacity = locked ? ".5" : "";
    });
  }

  /* -------------------- delegated click handler -------------------- */
  adminRoot.addEventListener("click", async (e) => {
    const btn = e.target.closest("button");
    if (!btn || !adminRoot.contains(btn)) return;

    /* chevron */
    if (btn.classList.contains("chevron-btn")) {
      e.stopPropagation();
      toggleRow(btn.closest("tr.main-row"));
      return;
    }

    /* Details */
    if (btn.classList.contains("details-btn")) {
      e.stopPropagation();
      toggleRow(btn.closest("tr.main-row"));
      return;
    }

    /* View screenshot */
    if (btn.classList.contains("view-shot")) {
      e.preventDefault();
      e.stopPropagation();
      openModal(btn.dataset.id, btn.dataset.code);
      return;
    }

    /* Approve */
    if (btn.classList.contains("approve-btn")) {
      e.preventDefault();
      e.stopPropagation();
      if (btn.disabled) return;
      const id = btn.dataset.id;
      if (!id) { console.warn("[admin] approve: missing data-id"); return; }
      if (!confirm("Approve this registration?")) return;

      const originalText = btn.textContent;
      btn.disabled = true;
      btn.textContent = "…";

      try {
        console.log("[admin] approve →", id);
        const res = await fetch("/admin/approve/" + id, {
          method: "POST",
          headers: { "Accept": "application/json" },
          credentials: "same-origin",
        });
        if (!res.ok) throw new Error("HTTP " + res.status);
        await res.json().catch(() => ({}));
        setRowStatus(btn.closest("tr.main-row"), "approved");
        applyFilters();
      } catch (err) {
        console.error("[admin] approve failed", err);
        alert("Failed to approve: " + err.message);
        btn.disabled = false;
        btn.textContent = originalText;
      }
      return;
    }

    /* Reject */
    if (btn.classList.contains("reject-btn")) {
      e.preventDefault();
      e.stopPropagation();
      if (btn.disabled) return;
      const id = btn.dataset.id;
      if (!id) { console.warn("[admin] reject: missing data-id"); return; }

      const notes = prompt("Reason for rejection (optional):", "");
      if (notes === null) return;

      const originalText = btn.textContent;
      btn.disabled = true;
      btn.textContent = "…";

      try {
        console.log("[admin] reject →", id);
        const res = await fetch("/admin/reject/" + id, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Accept":       "application/json",
          },
          credentials: "same-origin",
          body: JSON.stringify({ notes: notes }),
        });
        if (!res.ok) throw new Error("HTTP " + res.status);
        await res.json().catch(() => ({}));
        setRowStatus(btn.closest("tr.main-row"), "rejected");
        applyFilters();
      } catch (err) {
        console.error("[admin] reject failed", err);
        alert("Failed to reject: " + err.message);
        btn.disabled = false;
        btn.textContent = originalText;
      }
      return;
    }
  });

  /* -------------------- row body click toggles -------------------- */
  tbody?.addEventListener("click", (e) => {
    const row = e.target.closest("tr.main-row");
    if (!row || !tbody.contains(row)) return;
    if (e.target.closest("button, a, input, select, textarea")) return;
    toggleRow(row);
  });

  /* -------------------- expand all / collapse all -------------------- */
  expandAllBtn?.addEventListener("click", () => {
    const anyCollapsed = rows.some(
      (r) => r.style.display !== "none" && r.dataset.expanded !== "true"
    );
    rows.forEach((r) => {
      if (r.style.display !== "none") setExpanded(r, anyCollapsed);
    });
    expandAllBtn.textContent = anyCollapsed ? "Collapse all" : "Expand all";
  });

  /* -------------------- initial pass -------------------- */
  applyFilters();
  console.log("[admin] handlers attached — rows:", rows.length);
});