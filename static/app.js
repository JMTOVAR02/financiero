"use strict";

(() => {
  const $ = (selector) => document.querySelector(selector);
  const currentMonth = () => localDate().slice(0, 7);
  function localDate() {
    const now = new Date();
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  }
  const state = {
    data: null,
    month: currentMonth(),
    filter: "all",
    editingId: null,
    type: "expense",
    deleting: null,
    saving: false,
    deletingNow: false,
    requestId: 0,
  };
  const colors = [
    "#71955d",
    "#b7ca8b",
    "#d5ba83",
    "#91b9a6",
    "#d89a7b",
    "#c0afca",
    "#9bafba",
    "#e0d4a1",
    "#a8b99b",
  ];
  const arrowIcon = (income) =>
    income
      ? '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 6 6 18M6 8v10h10"/></svg>'
      : '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 18 18 6M8 6h10v10"/></svg>';
  let toastTimeout;
  const escape = (value) =>
    String(value).replace(
      /[&<>"']/g,
      (character) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[character],
    );
  function money(cents) {
    return new Intl.NumberFormat("es-ES", {
      style: "currency",
      currency: state.data?.currency || "EUR",
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(cents / 100);
  }
  function monthLabel(month, short = false) {
    const [year, number] = month.split("-").map(Number);
    return new Intl.DateTimeFormat("es-ES", {
      month: short ? "short" : "long",
      year: "numeric",
    }).format(new Date(year, number - 1, 1));
  }
  function dateLabel(date) {
    const [year, month, day] = date.split("-").map(Number);
    return new Intl.DateTimeFormat("es-ES", {
      day: "numeric",
      month: "short",
    }).format(new Date(year, month - 1, day));
  }
  async function api(url, options = {}) {
    let response;
    try {
      response = await fetch(url, {
        ...options,
        headers: {
          ...(options.body ? { "Content-Type": "application/json" } : {}),
          ...options.headers,
        },
      });
    } catch {
      throw new Error(
        "No se pudo conectar con la aplicación. Comprueba que Financiero sigue abierto en Terminal.",
      );
    }
    if (response.status === 204) return null;
    let body;
    try {
      body = await response.json();
    } catch {
      throw new Error(
        "El servidor no devolvió una respuesta válida. Reinicia Financiero e inténtalo de nuevo.",
      );
    }
    if (!response.ok)
      throw new Error(body.error || "No se pudo completar la operación.");
    return body;
  }
  function notify(message) {
    clearTimeout(toastTimeout);
    $("#toast").textContent = message;
    $("#toast").hidden = false;
    toastTimeout = setTimeout(() => {
      $("#toast").hidden = true;
    }, 4000);
  }
  async function loadData() {
    const requestId = ++state.requestId;
    $(".page").classList.add("is-loading");
    $("#connection-error").hidden = true;
    try {
      const data = await api(
        `/api/data?month=${encodeURIComponent(state.month)}`,
      );
      if (requestId !== state.requestId) return;
      state.data = data;
      render();
    } catch (error) {
      if (requestId !== state.requestId) return;
      if (state.data) {
        state.month = state.data.month;
        render();
      }
      $("#connection-error-text").textContent = error.message;
      $("#connection-error").hidden = false;
    } finally {
      if (requestId === state.requestId)
        $(".page").classList.remove("is-loading");
    }
  }
  function categoryLabel(type, category) {
    return (
      state.data.categories[type].find((entry) => entry.id === category)
        ?.label || category
    );
  }
  function render() {
    const { summary } = state.data;
    $("#summary-balance").textContent = money(summary.balance_cents);
    $("#summary-income").textContent = money(summary.income_cents);
    $("#summary-expense").textContent = money(summary.expense_cents);
    $("#total-balance").textContent = money(summary.total_balance_cents);
    $("#currency-select").value = state.data.currency;
    $("#amount-currency").textContent = state.data.currency;
    $("#month-picker").value = state.month;
    $("#previous-month").disabled = state.month === "1900-01";
    $("#next-month").disabled = state.month === "9999-12";
    $("#balance-caption").textContent =
      summary.transaction_count === 0
        ? "Un nuevo mes por delante"
        : summary.balance_cents >= 0
          ? "Ingresos menos gastos"
          : "Tus gastos superan tus ingresos";
    $("#movements-subtitle").textContent = monthLabel(state.month).replace(
      /^./,
      (letter) => letter.toUpperCase(),
    );
    $("#footer-month").textContent = monthLabel(state.month, true);
    $("#export-month").href =
      `/api/export.csv?month=${encodeURIComponent(state.month)}`;
    const previousCategory = $("#category-filter").value;
    const allCategories = new Map();
    Object.values(state.data.categories)
      .flat()
      .forEach((category) => allCategories.set(category.id, category.label));
    $("#category-filter").innerHTML =
      '<option value="all">Todas las categorías</option>' +
      [...allCategories]
        .sort((a, b) => a[1].localeCompare(b[1], "es"))
        .map(
          ([id, label]) =>
            `<option value="${escape(id)}">${escape(label)}</option>`,
        )
        .join("");
    if (allCategories.has(previousCategory))
      $("#category-filter").value = previousCategory;
    renderTransactions();
    renderChart();
    document.querySelectorAll("[data-add]").forEach((button) => {
      button.disabled = false;
    });
  }
  function renderTransactions() {
    if (!state.data) return;
    const search = $("#transaction-search")
      .value.trim()
      .toLocaleLowerCase("es")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "");
    const category = $("#category-filter").value;
    const transactions = state.data.transactions.filter((item) => {
      const text =
        `${item.description} ${categoryLabel(item.type, item.category)}`
          .toLocaleLowerCase("es")
          .normalize("NFD")
          .replace(/[\u0300-\u036f]/g, "");
      return (
        (state.filter === "all" || item.type === state.filter) &&
        (category === "all" || item.category === category) &&
        text.includes(search)
      );
    });
    const hasFilters = search || category !== "all" || state.filter !== "all";
    $("#transactions-count").textContent =
      `${transactions.length} ${transactions.length === 1 ? "movimiento" : "movimientos"}`;
    $("#transactions-table-wrap").hidden = transactions.length === 0;
    $("#empty-state").hidden = transactions.length !== 0;
    $("#empty-title").textContent = hasFilters
      ? "No hay coincidencias"
      : "Aquí empieza tu tranquilidad";
    $("#empty-description").textContent = hasFilters
      ? "Prueba otra búsqueda o cambia los filtros de este mes."
      : "Añade tu primer ingreso o gasto y empieza a ver tus finanzas con claridad.";
    $("#empty-add").hidden = Boolean(hasFilters);
    $("#clear-filters").hidden = !hasFilters;
    $("#transactions-body").innerHTML = transactions
      .map((item) => {
        const income = item.type === "income";
        const label = categoryLabel(item.type, item.category);
        return `<tr><td><div class="transaction-concept ${income ? "income" : ""}"><span class="row-icon" aria-hidden="true">${arrowIcon(income)}</span><span><span class="row-description">${escape(item.description)}</span><span class="row-mobile-meta">${escape(label)} · ${escape(dateLabel(item.date))}</span></span></div></td><td class="category-column category-cell"><span class="category-badge">${escape(label)}</span></td><td class="date-cell">${escape(dateLabel(item.date))}</td><td class="amount-cell ${income ? "income" : ""}">${income ? "+" : "−"}${escape(money(item.amount_cents))}</td><td><div class="row-actions"><button type="button" class="row-action" data-edit="${item.id}" aria-label="Editar ${escape(item.description)}" title="Editar"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m16 3 5 5-12 12-6 1 1-6Z"/><path d="m13 6 5 5"/></svg></button><button type="button" class="row-action delete" data-delete="${item.id}" aria-label="Eliminar ${escape(item.description)}" title="Eliminar"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7"/></svg></button></div></td></tr>`;
      })
      .join("");
  }
  function renderChart() {
    const total = state.data.summary.expense_cents;
    $("#chart-value").textContent = money(total);
    $("#chart-empty").hidden = total !== 0;
    const circumference = 2 * Math.PI * 63;
    let offset = 0;
    $("#chart-segments").innerHTML = state.data.breakdown
      .map((item, index) => {
        const length = (item.amount_cents / total) * circumference;
        const gap =
          state.data.breakdown.length > 1 ? Math.min(length / 6, 3) : 0;
        const circle = `<circle cx="80" cy="80" r="63" stroke="${colors[index % colors.length]}" stroke-dasharray="${Math.max(0, length - gap)} ${circumference - Math.max(0, length - gap)}" stroke-dashoffset="${-offset}"/>`;
        offset += length;
        return circle;
      })
      .join("");
    $("#category-breakdown").innerHTML = state.data.breakdown
      .map(
        (item, index) =>
          `<li><span class="category-name"><i style="background:${colors[index % colors.length]}"></i>${escape(item.label)}</span><span class="category-amount">${escape(money(item.amount_cents))}<small>${Math.round((item.amount_cents / total) * 100)} %</small></span></li>`,
      )
      .join("");
  }
  function setType(type, category) {
    state.type = type;
    document.querySelectorAll("[data-type]").forEach((button) => {
      const active = button.dataset.type === type;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    $("#category").innerHTML = state.data.categories[type]
      .map(
        (item) =>
          `<option value="${escape(item.id)}">${escape(item.label)}</option>`,
      )
      .join("");
    $("#category").value = category || (type === "expense" ? "food" : "salary");
  }
  function openTransaction(transaction = null) {
    if (!state.data || state.saving) return;
    state.editingId = transaction?.id || null;
    $("#transaction-form").reset();
    $("#amount").setCustomValidity("");
    $("#description").setCustomValidity("");
    $("#transaction-error").hidden = true;
    $("#transaction-title").textContent = transaction
      ? "Editar movimiento"
      : "Nuevo movimiento";
    $("#save-transaction").textContent = transaction
      ? "Guardar cambios"
      : "Guardar movimiento";
    $("#description").value = transaction?.description || "";
    $("#amount").value = transaction
      ? (transaction.amount_cents / 100).toFixed(2).replace(".", ",")
      : "";
    $("#date").value =
      transaction?.date ||
      (state.month === currentMonth() ? localDate() : `${state.month}-01`);
    setType(transaction?.type || "expense", transaction?.category);
    $("#transaction-dialog").showModal();
    $("#description").focus();
  }
  function changeMonth(delta) {
    const [year, month] = state.month.split("-").map(Number);
    const date = new Date(year, month - 1 + delta, 1);
    if (date.getFullYear() < 1900 || date.getFullYear() > 9999) return;
    state.month = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
    $("#month-picker").value = state.month;
    loadData();
  }
  function clearFilters() {
    $("#transaction-search").value = "";
    $("#category-filter").value = "all";
    setFilter("all");
  }
  function setFilter(filter) {
    state.filter = filter;
    document.querySelectorAll("[data-filter]").forEach((button) => {
      const active = button.dataset.filter === filter;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    renderTransactions();
  }
  $("#transaction-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (state.saving) return;
    const value = $("#amount").value.trim();
    const parts = value.replace(",", ".").split(".");
    const amount = /^\d+([.,]\d{1,2})?$/.test(value)
      ? Number(parts[0]) * 100 + Number((parts[1] || "").padEnd(2, "0"))
      : NaN;
    if (!Number.isSafeInteger(amount) || amount <= 0 || amount > 99999999999) {
      $("#amount").setCustomValidity(
        "Introduce un importe mayor que cero, sin separadores de miles y con un máximo de dos decimales.",
      );
      $("#amount").reportValidity();
      return;
    }
    if (!$("#description").value.trim()) {
      $("#description").setCustomValidity(
        "Escribe un concepto para este movimiento.",
      );
      $("#description").reportValidity();
      return;
    }
    const payload = {
      type: state.type,
      amount_cents: amount,
      description: $("#description").value.trim(),
      category: $("#category").value,
      date: $("#date").value,
    };
    state.saving = true;
    $("#save-transaction").disabled = true;
    $("#save-transaction").textContent = "Guardando…";
    $("#transaction-error").hidden = true;
    const editing = state.editingId;
    try {
      await api(
        editing ? `/api/transactions/${editing}` : "/api/transactions",
        { method: editing ? "PUT" : "POST", body: JSON.stringify(payload) },
      );
      $("#transaction-dialog").close();
      state.month = payload.date.slice(0, 7);
      clearFilters();
      await loadData();
      notify(
        editing
          ? "Cambios guardados en tu equipo."
          : "Movimiento guardado en tu equipo.",
      );
    } catch (error) {
      $("#transaction-error").textContent = error.message;
      $("#transaction-error").hidden = false;
    } finally {
      state.saving = false;
      $("#save-transaction").disabled = false;
      $("#save-transaction").textContent = state.editingId
        ? "Guardar cambios"
        : "Guardar movimiento";
    }
  });
  $("#amount").addEventListener("input", () => {
    $("#amount").setCustomValidity("");
  });
  $("#description").addEventListener("input", () => {
    $("#description").setCustomValidity("");
  });
  document.querySelectorAll("[data-add]").forEach((button) => {
    button.disabled = true;
    button.addEventListener("click", () => openTransaction());
  });
  document.querySelectorAll("[data-type]").forEach((button) => {
    button.addEventListener("click", () => setType(button.dataset.type));
  });
  document.querySelectorAll(".close-dialog").forEach((button) => {
    button.addEventListener("click", () => {
      if (!state.saving) $("#transaction-dialog").close();
    });
  });
  $("#transaction-dialog").addEventListener("cancel", (event) => {
    if (state.saving) event.preventDefault();
  });
  document.querySelectorAll("[data-filter]").forEach((button) => {
    button.addEventListener("click", () => setFilter(button.dataset.filter));
  });
  $("#transaction-search").addEventListener("input", renderTransactions);
  $("#category-filter").addEventListener("change", renderTransactions);
  $("#clear-filters").addEventListener("click", clearFilters);
  $("#previous-month").addEventListener("click", () => changeMonth(-1));
  $("#next-month").addEventListener("click", () => changeMonth(1));
  $("#month-picker").value = state.month;
  $("#month-picker").addEventListener("change", (event) => {
    if (
      !event.target.checkValidity() ||
      !/^\d{4}-\d{2}$/.test(event.target.value)
    ) {
      event.target.value = state.month;
      return;
    }
    state.month = event.target.value;
    loadData();
  });
  $("#retry-button").addEventListener("click", loadData);
  $("#transactions-body").addEventListener("click", (event) => {
    const edit = event.target.closest("[data-edit]");
    const remove = event.target.closest("[data-delete]");
    if (edit)
      openTransaction(
        state.data.transactions.find(
          (item) => item.id === Number(edit.dataset.edit),
        ),
      );
    if (remove) {
      state.deleting = state.data.transactions.find(
        (item) => item.id === Number(remove.dataset.delete),
      );
      $("#delete-description").textContent =
        `${state.deleting.description} · ${money(state.deleting.amount_cents)}`;
      $("#delete-error").hidden = true;
      $("#delete-dialog").showModal();
      $("#cancel-delete").focus();
    }
  });
  for (const id of ["#close-delete", "#cancel-delete"])
    $(id).addEventListener("click", () => {
      if (!state.deletingNow) $("#delete-dialog").close();
    });
  $("#delete-dialog").addEventListener("cancel", (event) => {
    if (state.deletingNow) event.preventDefault();
  });
  $("#confirm-delete").addEventListener("click", async () => {
    if (!state.deleting || state.deletingNow) return;
    state.deletingNow = true;
    $("#confirm-delete").disabled = true;
    $("#delete-error").hidden = true;
    try {
      await api(`/api/transactions/${state.deleting.id}`, {
        method: "DELETE",
        body: "{}",
      });
      $("#delete-dialog").close();
      state.deleting = null;
      await loadData();
      notify("Movimiento eliminado.");
    } catch (error) {
      $("#delete-error").textContent = error.message;
      $("#delete-error").hidden = false;
    } finally {
      state.deletingNow = false;
      $("#confirm-delete").disabled = false;
    }
  });
  $("#currency-select").addEventListener("change", async (event) => {
    const currency = event.target.value;
    event.target.disabled = true;
    try {
      await api("/api/settings", {
        method: "PUT",
        body: JSON.stringify({ currency }),
      });
      await loadData();
      notify("Moneda actualizada. Los importes no se convierten.");
    } catch (error) {
      if (state.data) event.target.value = state.data.currency;
      notify(error.message);
    } finally {
      event.target.disabled = false;
    }
  });
  loadData();
})();
