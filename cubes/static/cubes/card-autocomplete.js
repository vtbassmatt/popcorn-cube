// Scryfall autocomplete + card preview for the submission form.
(function () {
  "use strict";

  const AUTOCOMPLETE_URL = "https://api.scryfall.com/cards/autocomplete";
  const NAMED_URL = "https://api.scryfall.com/cards/named";
  const DEBOUNCE_MS = 250;
  const MIN_CHARS = 2;

  const input = document.getElementById("id_card_name");
  if (!input) return;

  // --- Autocomplete dropdown ---
  const wrapper = document.createElement("div");
  wrapper.style.position = "relative";
  input.parentNode.insertBefore(wrapper, input);
  wrapper.appendChild(input);

  const listbox = document.createElement("ul");
  listbox.className = "list-group shadow";
  listbox.style.cssText =
    "position:absolute;z-index:1050;width:100%;max-height:260px;overflow-y:auto;display:none;";
  listbox.setAttribute("role", "listbox");
  listbox.id = "card-name-listbox";
  wrapper.appendChild(listbox);

  input.setAttribute("autocomplete", "off");
  input.setAttribute("role", "combobox");
  input.setAttribute("aria-autocomplete", "list");
  input.setAttribute("aria-controls", "card-name-listbox");
  input.setAttribute("aria-expanded", "false");

  let debounceTimer = null;
  let activeIndex = -1;
  let currentItems = [];

  function showList(names) {
    currentItems = names;
    activeIndex = -1;
    listbox.innerHTML = "";
    if (!names.length) {
      listbox.style.display = "none";
      input.setAttribute("aria-expanded", "false");
      return;
    }
    names.forEach((name, i) => {
      const li = document.createElement("li");
      li.className = "list-group-item list-group-item-action py-1 px-2";
      li.style.cursor = "pointer";
      li.textContent = name;
      li.setAttribute("role", "option");
      li.addEventListener("mousedown", (e) => {
        e.preventDefault(); // keep focus on input
        selectName(name);
      });
      listbox.appendChild(li);
    });
    listbox.style.display = "block";
    input.setAttribute("aria-expanded", "true");
  }

  function highlightItem(index) {
    const items = listbox.children;
    for (let i = 0; i < items.length; i++) {
      items[i].classList.toggle("active", i === index);
    }
    if (items[index]) items[index].scrollIntoView({ block: "nearest" });
  }

  function selectName(name) {
    input.value = name;
    listbox.style.display = "none";
    input.setAttribute("aria-expanded", "false");
    fetchPreview(name);
  }

  function fetchAutocomplete(q) {
    fetch(`${AUTOCOMPLETE_URL}?q=${encodeURIComponent(q)}`)
      .then((r) => r.json())
      .then((data) => {
        if (data.object === "catalog" && data.data) {
          showList(data.data);
        }
      })
      .catch(() => {});
  }

  input.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    clearPreview();
    const q = input.value.trim();
    if (q.length < MIN_CHARS) {
      showList([]);
      return;
    }
    debounceTimer = setTimeout(() => fetchAutocomplete(q), DEBOUNCE_MS);
  });

  input.addEventListener("keydown", (e) => {
    if (listbox.style.display === "none") return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      activeIndex = Math.min(activeIndex + 1, currentItems.length - 1);
      highlightItem(activeIndex);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      activeIndex = Math.max(activeIndex - 1, 0);
      highlightItem(activeIndex);
    } else if (e.key === "Enter" && activeIndex >= 0) {
      e.preventDefault();
      selectName(currentItems[activeIndex]);
    } else if (e.key === "Escape") {
      showList([]);
    }
  });

  input.addEventListener("blur", () => {
    // Small delay so mousedown on list item fires first
    setTimeout(() => {
      listbox.style.display = "none";
      input.setAttribute("aria-expanded", "false");
    }, 150);
  });

  // --- Card preview ---
  const previewContainer = document.createElement("div");
  previewContainer.id = "card-preview";
  previewContainer.className = "mt-3";
  previewContainer.style.display = "none";

  const previewImg = document.createElement("img");
  previewImg.className = "rounded shadow";
  previewImg.style.maxWidth = "250px";
  previewImg.alt = "Card preview";

  const previewName = document.createElement("p");
  previewName.className = "mt-1 mb-0 fw-semibold small";

  previewContainer.appendChild(previewImg);
  previewContainer.appendChild(previewName);

  // Insert preview after the card_name field's parent <p>
  const fieldParent = wrapper.closest("p") || wrapper.parentNode;
  fieldParent.after(previewContainer);

  function clearPreview() {
    previewContainer.style.display = "none";
    previewImg.src = "";
    previewName.textContent = "";
  }

  function fetchPreview(cardName) {
    clearPreview();
    fetch(
      `${NAMED_URL}?exact=${encodeURIComponent(cardName)}&format=json`
    )
      .then((r) => {
        if (!r.ok) throw new Error(r.status);
        return r.json();
      })
      .then((card) => {
        let imgUrl = null;
        if (card.image_uris) {
          imgUrl = card.image_uris.normal || card.image_uris.small;
        } else if (card.card_faces && card.card_faces[0]?.image_uris) {
          imgUrl =
            card.card_faces[0].image_uris.normal ||
            card.card_faces[0].image_uris.small;
        }
        if (imgUrl) {
          previewImg.src = imgUrl;
          previewName.textContent = card.name;
          previewContainer.style.display = "block";
        }
      })
      .catch(() => clearPreview());
  }

  // If the field already has a value on page load (e.g. validation error),
  // show the preview immediately.
  if (input.value.trim().length >= MIN_CHARS) {
    fetchPreview(input.value.trim());
  }
})();
