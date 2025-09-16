function saveOptions() {
  const whitelist = document.getElementById("whitelist").value.split("\n");
  const settings = {
    whitelistedDomains: {},
    statusIndicators: document.getElementById("status_indicators").checked,
  };

  whitelist.forEach((line) => {
    line = line
      .trim()
      .replace(/^\w*\:?\/+/i, "")
      .replace(/^w{2,3}\d*\./i, "")
      .split("/")[0]
      .split(":")[0];

    if (line.length > 0 && line.length < 100) {
      settings.whitelistedDomains[line] = true;
    }
  });

  chrome.storage.local.set({ settings }, () => {
    document.getElementById("status_saved").style.display = "inline";

    setTimeout(function () {
      document.getElementById("status_saved").style.display = "none";
    }, 2000);

    chrome.runtime.sendMessage("update_settings");
  });
}

function restoreOptions() {
  chrome.storage.local.get(
    { settings: { whitelistedDomains: {}, statusIndicators: true } },
    ({ settings }) => {
      document.getElementById("whitelist").value = Object.keys(
        settings.whitelistedDomains
      )
        .sort()
        .join("\n");
      document.getElementById("status_indicators").checked =
        settings.statusIndicators;
    }
  );
}

document.title = document.getElementById("title").textContent =
  chrome.i18n.getMessage("optionsTitle") +
  " - " +
  chrome.i18n.getMessage("extensionName");
document.getElementById("whitelist_label").textContent =
  chrome.i18n.getMessage("optionsWhitelist");
document.getElementById("status_indicators_label").textContent =
  chrome.i18n.getMessage("optionStatusIndicators");

document
  .getElementById("save")
  .setAttribute("value", chrome.i18n.getMessage("optionsButton"));
document.getElementById("status_saved").textContent =
  chrome.i18n.getMessage("optionsSaved");

document.addEventListener("DOMContentLoaded", restoreOptions);
document.getElementById("save").addEventListener("click", saveOptions);
