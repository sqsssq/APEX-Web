/**
 * Team page renderer
 * - Reads assets/data/team.json
 * - Renders Team + Alumni cards with role-based classes
 */
(function () {
  "use strict";

  function qs(id) {
    return document.getElementById(id);
  }

  function escapeHtml(str) {
    return String(str || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function roleToClass(role) {
    switch (role) {
      case "faculty":
        return "role-faculty";
      case "admin":
        return "role-admin";
      case "phd":
        return "role-phd";
      case "mphil":
        return "role-mphil";
      case "phd-mphil":
        return "role-phd-mphil";
      case "visiting-ra":
      case "visiting":
      case "ra":
        return "role-visiting-ra";
      default:
        return "";
    }
  }

  function renderCard(member, delay) {
    var name = escapeHtml(member.name);
    var title = escapeHtml(member.title);
    var time = escapeHtml(member.time);
    var note = escapeHtml(member.note || "");
    var destination = escapeHtml(member.destination || "");
    var photo = escapeHtml(member.photo || "");
    var link = escapeHtml(member.link || "");
    var roleClass = roleToClass(member.role);

    var cardInner =
      '<div class="team-member d-flex flex-column ' +
      roleClass +
      '">' +
      (photo
        ? '<div class="pic"><img src="' +
          photo +
          '" class="img-fluid" alt="' +
          name +
          '" loading="lazy" decoding="async"></div>'
        : "") +
      '<div class="member-info p-0">' +
      '<h4 class="mb-1">' +
      name +
      "</h4>" +
      '<span class="pb-0">' +
      title +
      "</span>" +
      '<p class="mb-0"><small>' +
      time +
      "</small></p>" +
      (note ? '<p class="mb-0"><small>' + note + "</small></p>" : "") +
      (destination
        ? '<p class="mb-0"><small>' + destination + "</small></p>"
        : "") +
      "</div>" +
      "</div>";

    var wrapper =
      link
        ? '<a class="team-card-link" href="' +
          link +
          '" target="_blank" rel="noopener noreferrer">' +
          cardInner +
          "</a>"
        : '<div class="team-card-static">' + cardInner + "</div>";

    return (
      '<div class="team-col col-12 col-md-6" data-aos="fade-up" data-aos-delay="' +
      delay +
      '">' +
      wrapper +
      "</div>"
    );
  }

  function renderList(container, list) {
    if (!container) return;
    var html = "";
    var delay = 0;
    list.forEach(function (m, idx) {
      html += renderCard(m, delay);
    });
    container.innerHTML = html;
  }

  var teamGrid = qs("team-grid");
  var alumniGrid = qs("alumni-grid");
  var errorBox = qs("team-data-error");

  fetch("assets/data/team.json", { cache: "no-store" })
    .then(function (res) {
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.json();
    })
    .then(function (data) {
      if (errorBox) errorBox.remove();
      renderList(teamGrid, Array.isArray(data.team) ? data.team : []);
      renderList(alumniGrid, Array.isArray(data.alumni) ? data.alumni : []);

      // If AOS is loaded, refresh to apply animations on injected nodes.
      if (window.AOS && typeof window.AOS.refresh === "function") {
        window.AOS.refresh();
      }
    })
    .catch(function (err) {
      if (errorBox) {
        errorBox.style.display = "block";
        errorBox.textContent =
          "Team 数据加载失败（assets/data/team.json）。如果你是直接用 file:// 打开页面，浏览器可能会拦截 fetch；请用本地静态服务器打开。错误：" +
          String(err && err.message ? err.message : err);
      }
    });
})();

