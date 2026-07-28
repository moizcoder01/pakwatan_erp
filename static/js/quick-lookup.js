/**
 * static/js/quick-lookup.js
 * ---------------------------------------------------------------
 * Shared AJAX wiring for the "360-Degree Info Card" quick lookup
 * boxes on Guards, Weapons, and Clients pages. This module only
 * handles: submit -> fetch -> loading/error state -> render ->
 * close button. Each page supplies its own `render(data)` function
 * that returns the page-specific card markup.
 * ---------------------------------------------------------------
 */

function initQuickLookup(options) {
    var form = document.getElementById(options.formId);
    var input = document.getElementById(options.inputId);
    var cardContainer = document.getElementById(options.cardContainerId);

    if (!form || !input || !cardContainer) return;

    form.addEventListener("submit", function (e) {
        e.preventDefault();
        var value = input.value.trim();
        if (!value) {
            renderMessage(cardContainer, "Please enter a value to search.", "amber");
            return;
        }
        runLookup(value);
    });

    function runLookup(value) {
        renderLoading(cardContainer);

        var url = options.endpoint + "?" + encodeURIComponent(options.paramName) +
            "=" + encodeURIComponent(value);

        fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" } })
            .then(function (res) {
                return res.json().then(function (json) {
                    return { ok: res.ok, json: json };
                });
            })
            .then(function (result) {
                if (!result.ok || !result.json.success) {
                    var msg = (result.json && result.json.error) || "No matching record found.";
                    renderMessage(cardContainer, msg, "red");
                    return;
                }
                cardContainer.innerHTML = options.render(result.json.data);
                wireCloseButton(cardContainer);
            })
            .catch(function () {
                renderMessage(cardContainer, "Network error — please try again.", "red");
            });
    }

    function wireCloseButton(container) {
        var closeBtn = container.querySelector("[data-lookup-close]");
        if (closeBtn) {
            closeBtn.addEventListener("click", function () {
                container.innerHTML = "";
                container.classList.remove("is-visible");
            });
        }
        container.classList.add("is-visible");
    }

    function renderLoading(container) {
        container.classList.add("is-visible");
        container.innerHTML =
            '<div class="info-card info-card--loading">' +
            '<span class="led led--amber"></span> Searching records…' +
            "</div>";
    }

    function renderMessage(container, message, tone) {
        container.classList.add("is-visible");
        container.innerHTML =
            '<div class="info-card info-card--message">' +
            '<span class="led led--' + tone + '"></span>' +
            "<span>" + escapeHtml(message) + "</span>" +
            '<button type="button" class="info-card__close" data-lookup-close aria-label="Dismiss">&times;</button>' +
            "</div>";
        wireCloseButton(container);
    }

    function escapeHtml(str) {
        var div = document.createElement("div");
        div.textContent = str;
        return div.innerHTML;
    }
}