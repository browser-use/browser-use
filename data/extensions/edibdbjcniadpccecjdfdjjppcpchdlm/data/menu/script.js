const toggle = document.getElementById("toggle");
const refresh = document.getElementById("refresh");
const report = document.getElementById("report");
const options = document.getElementById("options");

const issueTypeSelect = document.getElementById("report_issue_type");
const reportNotesTextarea = document.getElementById("report-notes");

let currentTab = false;

toggle.addEventListener("click", function (e) {
  chrome.runtime.sendMessage(
    {
      command: "toggle_extension",
      tabId: currentTab.id,
    },
    () => reloadMenu(true)
  );
});

refresh.addEventListener("click", function (e) {
  chrome.runtime.sendMessage(
    {
      command: "refresh_page",
      tabId: currentTab.id,
    },
    () => window.close()
  );
});

options.addEventListener("click", function (e) {
  chrome.runtime.sendMessage(
    {
      command: "open_options_page",
    },
    () => window.close()
  );
});

report.addEventListener("click", () => switchMenu("menu_report"));
document
  .getElementById("error_back_button")
  .addEventListener("click", () => switchMenu("menu_main"));

document.getElementById("report_github").addEventListener("click", () =>
  chrome.runtime.sendMessage(
    {
      command: "report_website",
      tabId: currentTab.id,
      anon: false,
    },
    () => window.close()
  )
);

document.getElementById("report_anon").addEventListener("click", function (e) {
  switchMenu("menu_report_anon");
  document.getElementById("hostname").textContent = currentTab.hostname;
});

issueTypeSelect.addEventListener("change", () => {
  let issueTypeValue =
    issueTypeSelect.options[issueTypeSelect.selectedIndex].value;

  document
    .querySelectorAll("label[id*='issue_description']")
    .forEach((label) => {
      label.style.display = "none";
    });

  reportNotesTextarea.style.display =
    issueTypeValue == "general" ? "block" : "none";
  document.getElementById(`${issueTypeValue}_issue_description`).style.display =
    "block";
});

document.getElementById("report_anon_send").addEventListener("click", () => {
  let issueTypeValue =
    issueTypeSelect.options[issueTypeSelect.selectedIndex].value;

  switchMenu("menu_loading");
  chrome.runtime.sendMessage(
    {
      command: "report_website",
      tabId: currentTab.id,
      anon: true,
      issueType: issueTypeValue,
      notes: issueTypeValue == "general" ? reportNotesTextarea.value : null,
    },
    (message) => {
      if (message.error) {
        switchMenu("menu_error");
      } else {
        window.close();
      }
    }
  );
});

document
  .getElementById("report_anon_cancel")
  .addEventListener("click", () => window.close());

function reloadMenu(enableRefreshButton) {
  translate();
  chrome.tabs.query({ active: true, currentWindow: true }, function (tabs) {
    chrome.runtime.sendMessage(
      {
        command: "get_active_tab",
        tabId: tabs[0].id,
      },
      function (message) {
        message = message || {};
        currentTab = message.tab ? message.tab : false;

        if (message.tab && message.tab.hostname) {
          toggle.textContent = chrome.i18n.getMessage(
            message.tab.whitelisted ? "menuEnable" : "menuDisable",
            message.tab.hostname
          );
          toggle.style.display = "block";

          report.style.display = message.tab.whitelisted ? "none" : "block";
        } else {
          toggle.textContent = "";
          toggle.style.display = "none";
          report.style.display = "none";
        }

        if (typeof enableRefreshButton != "undefined") {
          refresh.style.display = "block";
          toggle.style.display = "none";
          report.style.display = "none";
        }
      }
    );
  });
}

function switchMenu(id) {
  const menus = document.getElementsByClassName("menu");
  for (let i = 0; i < menus.length; i++) {
    if (menus[i].id != id) {
      menus[i].classList.add("menu-hidden");
    } else {
      menus[i].classList.remove("menu-hidden");
    }
  }
}

function translate() {
  for (const element of document.querySelectorAll("[data-translate]")) {
    element.textContent = chrome.i18n.getMessage(element.dataset.translate);
  }

  reportNotesTextarea.placeholder = chrome.i18n.getMessage(
    "reportNotesPlaceholder"
  );
}

reloadMenu();
