const menuToggle = document.querySelector("[data-menu-toggle]");
const nav = document.querySelector("[data-nav]");
const modal = document.querySelector("[data-offer-modal]");
const openOfferButtons = document.querySelectorAll("[data-open-offer]");
const closeOffer = document.querySelector("[data-close-offer]");
const loginModal = document.querySelector("[data-login-modal]");
const openLoginButtons = document.querySelectorAll("[data-open-login]");
const closeLogin = document.querySelector("[data-close-login]");
const loginForm = document.querySelector("[data-login-form]");
const loginNotice = document.querySelector("[data-login-notice]");
const faqItems = document.querySelectorAll(".faq-list details");
const buttons = document.querySelectorAll(".btn, .header-cta, .menu-toggle, .footer-link");
const sectionLinks = [...document.querySelectorAll('.main-nav a[href^="#"]')];
const linkedSections = sectionLinks
  .map((link) => document.querySelector(link.getAttribute("href")))
  .filter(Boolean);

const openOfferModal = () => {
  if (modal instanceof HTMLDialogElement) {
    modal.showModal();
    document.documentElement.classList.add("modal-open");
  }
};

const closeOfferModal = () => {
  if (modal instanceof HTMLDialogElement) {
    modal.close();
  }
};

const closeMenu = () => {
  if (!menuToggle || !nav) return;
  nav.classList.remove("is-open");
  menuToggle.setAttribute("aria-expanded", "false");
  document.body.classList.remove("menu-open");
};

menuToggle?.addEventListener("click", () => {
  const isOpen = nav.classList.toggle("is-open");
  menuToggle.setAttribute("aria-expanded", String(isOpen));
  document.body.classList.toggle("menu-open", isOpen);
});

nav?.addEventListener("click", (event) => {
  if (event.target instanceof HTMLAnchorElement) {
    setActiveNavLink(event.target.hash.slice(1));
    closeMenu();
  }
});

openOfferButtons.forEach((button) => {
  button.addEventListener("click", openOfferModal);
});

closeOffer?.addEventListener("click", closeOfferModal);

modal?.addEventListener("click", (event) => {
  if (event.target === modal && modal instanceof HTMLDialogElement) {
    closeOfferModal();
  }
});

modal?.addEventListener("close", () => {
  document.documentElement.classList.remove("modal-open");
});

const openLoginModal = () => {
  if (loginModal instanceof HTMLDialogElement) {
    loginNotice?.classList.remove("is-visible");
    loginForm?.reset();
    loginModal.showModal();
    document.documentElement.classList.add("modal-open");
  }
};

const closeLoginModal = () => {
  if (loginModal instanceof HTMLDialogElement) {
    loginModal.close();
  }
};

openLoginButtons.forEach((button) => {
  button.addEventListener("click", openLoginModal);
});

closeLogin?.addEventListener("click", closeLoginModal);

loginModal?.addEventListener("click", (event) => {
  if (event.target === loginModal && loginModal instanceof HTMLDialogElement) {
    closeLoginModal();
  }
});

loginModal?.addEventListener("close", () => {
  document.documentElement.classList.remove("modal-open");
});

loginForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  loginNotice?.classList.add("is-visible");
});

faqItems.forEach((item) => {
  item.addEventListener("toggle", () => {
    if (!item.open) return;

    faqItems.forEach((otherItem) => {
      if (otherItem !== item) {
        otherItem.open = false;
      }
    });
  });
});

buttons.forEach((button) => {
  button.addEventListener("pointerdown", (event) => {
    const ripple = document.createElement("span");
    const rect = button.getBoundingClientRect();
    const size = Math.max(rect.width, rect.height);

    ripple.className = "ripple";
    ripple.style.width = `${size}px`;
    ripple.style.height = `${size}px`;
    ripple.style.left = `${event.clientX - rect.left - size / 2}px`;
    ripple.style.top = `${event.clientY - rect.top - size / 2}px`;

    button.querySelector(".ripple")?.remove();
    button.append(ripple);
  });
});

const revealItems = document.querySelectorAll(".reveal");

if ("IntersectionObserver" in window) {
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.12, rootMargin: "0px 0px -40px 0px" },
  );

  revealItems.forEach((item) => observer.observe(item));
} else {
  revealItems.forEach((item) => item.classList.add("is-visible"));
}

const setActiveNavLink = (sectionId) => {
  sectionLinks.forEach((link) => {
    const isCurrent = Boolean(sectionId) && link.getAttribute("href") === `#${sectionId}`;
    link.classList.toggle("is-active", isCurrent);

    if (isCurrent) {
      link.setAttribute("aria-current", "true");
    } else {
      link.removeAttribute("aria-current");
    }
  });
};

let navTicking = false;

const updateActiveNav = () => {
  if (linkedSections.length === 0) return;

  const headerHeight = document.querySelector(".site-header")?.offsetHeight ?? 0;
  const marker = window.scrollY + headerHeight + 96;
  const firstSection = linkedSections[0];

  if (marker < firstSection.offsetTop) {
    setActiveNavLink(null);
    return;
  }

  let currentSection = firstSection;

  linkedSections.forEach((section) => {
    if (section.offsetTop <= marker) {
      currentSection = section;
    }
  });

  setActiveNavLink(currentSection.id);
};

const requestActiveNavUpdate = () => {
  if (navTicking) return;

  navTicking = true;
  window.requestAnimationFrame(() => {
    updateActiveNav();
    navTicking = false;
  });
};

window.addEventListener("scroll", requestActiveNavUpdate, { passive: true });
window.addEventListener("resize", requestActiveNavUpdate);
window.addEventListener("hashchange", () => window.setTimeout(updateActiveNav, 120));
updateActiveNav();
