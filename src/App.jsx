import React, { useEffect, useRef, useState } from "react";
import {
  ArrowUpRight,
  ArrowRight,
  ArrowDown,
  Phone,
  MapPin,
  Plus,
  Menu,
  X,
  ShoppingBag,
  Pizza,
  Heart,
  Flame,
  Leaf,
  Clock,
  ChevronDown,
  Check,
  Navigation,
} from "lucide-react";
import OrderDrawer from "./components/OrderDrawer";

const PHONE = "tel:+61354060779";
const MAPS =
  "https://www.google.com/maps/search/?api=1&query=Say+Cheese+Pizza+731+Calder+Hwy+Maiden+Gully+VIC+3551";
const pizzas = [
  {
    id: "margherita",
    name: "Margherita",
    category: "Veggie",
    price: 18,
    ingredients: "Rich tomato, mozzarella, fresh basil. Simple for a reason.",
    image: "pizza-1",
    tag: "THE CLASSIC",
    veggie: true,
  },
  {
    id: "pepperoni",
    name: "Pepperoni",
    category: "Classics",
    price: 21,
    ingredients: "Generous pepperoni, melting mozzarella, our tomato base.",
    image: "pizza-2",
    tag: "CROWD FAVOURITE",
  },
  {
    id: "meat-lovers",
    name: "BBQ Meat Lovers",
    category: "Meat lovers",
    price: 24,
    ingredients: "Ham, bacon, beef & pepperoni. Finished with smoky BBQ.",
    image: "pizza-3",
    tag: "",
  },
  {
    id: "garden",
    name: "Garden Party",
    category: "Veggie",
    price: 22,
    ingredients: "Capsicum, mushroom, red onion, olives & a little local love.",
    image: "pizza-4",
    tag: "VEGGIE GOODNESS",
    veggie: true,
  },
  {
    id: "hawaiian",
    name: "Hawaiian",
    category: "Classics",
    price: 21,
    ingredients: "Smoky ham, sweet pineapple & mozzarella. Pick your side.",
    image: "pizza-2",
  },
  {
    id: "gully",
    name: "The Gully Special",
    category: "Meat lovers",
    price: 25,
    ingredients: "Pepperoni, ham, mushroom, capsicum & olives. The works.",
    image: "pizza-3",
    tag: "LOCAL INSPIRATION",
  },
  {
    id: "chicken",
    name: "BBQ Chicken",
    category: "Meat lovers",
    price: 24,
    ingredients: "Chicken, bacon, red onion & a generous swirl of BBQ sauce.",
    image: "pizza-3",
  },
  {
    id: "mushroom",
    name: "Mushroom Magic",
    category: "Veggie",
    price: 22,
    ingredients: "Earthy mushrooms, garlic, mozzarella & fragrant herbs.",
    image: "pizza-4",
    veggie: true,
  },
  {
    id: "supreme",
    name: "Supreme",
    category: "Classics",
    price: 24,
    ingredients: "Ham, pepperoni, pineapple, capsicum, mushroom & olives.",
    image: "pizza-3",
  },
  {
    id: "chilli",
    name: "A Little Heat",
    category: "Meat lovers",
    price: 23,
    ingredients: "Pepperoni, jalapeño, red onion & chilli. Bring the heat.",
    image: "pizza-2",
    tag: "FEEL THE HEAT",
  },
  {
    id: "cheese",
    name: "Say More Cheese",
    category: "Veggie",
    price: 20,
    ingredients: "Mozzarella, parmesan & a golden, gloriously cheesy finish.",
    image: "pizza-1",
    veggie: true,
  },
  {
    id: "garlic",
    name: "Garlic & Herb",
    category: "Classics",
    price: 16,
    ingredients: "Garlic butter, mozzarella & herbs. Made for sharing.",
    image: "pizza-1",
  },
];

function Logo({ footer = false, onClick }) {
  return (
    <a
      className={`logo ${footer ? "footer-logo" : ""}`}
      href="#home"
      aria-label="Say Cheese Pizza home"
      onClick={onClick}
    >
      <span className="logo-icon">
        <Pizza size={35} strokeWidth={1.7} />
      </span>
      <span className="logo-type">
        say cheese<span>PIZZA · MAIDEN GULLY</span>
      </span>
    </a>
  );
}

function loadOrder() {
  try {
    const stored = JSON.parse(localStorage.getItem("say-cheese-order") || "[]");
    if (!Array.isArray(stored)) return [];
    return stored
      .filter(
        (item) =>
          pizzas.some((pizza) => pizza.id === item.id) &&
          Number.isInteger(item.quantity) &&
          item.quantity > 0,
      )
      .map((item) => ({
        ...pizzas.find((pizza) => pizza.id === item.id),
        quantity: Math.min(item.quantity, 20),
      }));
  } catch {
    return [];
  }
}

function App() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [category, setCategory] = useState("All pizzas");
  const [expanded, setExpanded] = useState(false);
  const [items, setItems] = useState(loadOrder);
  const [cartOpen, setCartOpen] = useState(false);
  const [toast, setToast] = useState("");
  const [mapZoom, setMapZoom] = useState(1);
  const toastTimer = useRef();
  const bagButtonRef = useRef();
  const orderOpenerRef = useRef();
  const mobileToggleRef = useRef();
  const count = items.reduce((total, item) => total + item.quantity, 0);
  const filtered =
    category === "All pizzas"
      ? pizzas
      : pizzas.filter(
          (pizza) =>
            pizza.category === category ||
            (category === "Classics" && pizza.id === "margherita"),
        );
  const shown =
    category === "All pizzas" && !expanded ? filtered.slice(0, 4) : filtered;

  useEffect(() => {
    try {
      localStorage.setItem(
        "say-cheese-order",
        JSON.stringify(items.map(({ id, quantity }) => ({ id, quantity }))),
      );
    } catch {
      /* Order still works without storage. */
    }
  }, [items]);
  useEffect(() => () => clearTimeout(toastTimer.current), []);
  useEffect(() => {
    if (!menuOpen) return;
    const close = (event) => {
      if (event.key === "Escape") {
        setMenuOpen(false);
        mobileToggleRef.current?.focus();
      }
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [menuOpen]);

  function addPizza(pizza) {
    if (items.find((item) => item.id === pizza.id)?.quantity >= 20) {
      setToast("For more than 20 of one pizza, please call the shop.");
      clearTimeout(toastTimer.current);
      toastTimer.current = setTimeout(() => setToast(""), 4000);
      return;
    }
    setItems((current) => {
      const existing = current.find((item) => item.id === pizza.id);
      return existing
        ? current.map((item) =>
            item.id === pizza.id
              ? { ...item, quantity: Math.min(20, item.quantity + 1) }
              : item,
          )
        : [...current, { ...pizza, quantity: 1 }];
    });
    setToast(`${pizza.name} added to your order`);
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(""), 3000);
  }

  function changeQuantity(id, quantity) {
    setItems((current) =>
      quantity <= 0
        ? current.filter((item) => item.id !== id)
        : current.map((item) =>
            item.id === id
              ? { ...item, quantity: Math.min(20, quantity) }
              : item,
          ),
    );
  }

  const closeMenu = () => setMenuOpen(false);
  const openOrder = (event) => {
    orderOpenerRef.current = event.currentTarget;
    setCartOpen(true);
  };

  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="site-header" id="home">
        <div className="container header-inner">
          <Logo onClick={closeMenu} />
          <nav
            className={menuOpen ? "main-nav is-open" : "main-nav"}
            aria-label="Main navigation"
            id="main-navigation"
          >
            <a href="#menu" onClick={closeMenu}>
              Our menu
            </a>
            <a href="#story" onClick={closeMenu}>
              Our story
            </a>
            <a href="#reviews" onClick={closeMenu}>
              Local love
            </a>
            <a href="#visit" onClick={closeMenu}>
              Find us <ArrowUpRight size={13} />
            </a>
            <a href={PHONE} className="mobile-phone">
              <Phone size={16} /> (03) 5406 0779
            </a>
          </nav>
          <div className="header-actions">
            <button
              className="bag-button"
              ref={bagButtonRef}
              onClick={openOrder}
              aria-label={`Open your order, ${count} ${count === 1 ? "item" : "items"}`}
            >
              <ShoppingBag size={20} />
              {count > 0 && <span className="bag-count">{count}</span>}
            </button>
            <a className="button button-amber header-order" href="#menu">
              Let’s order <ArrowUpRight size={17} />
            </a>
            <button
              className="mobile-toggle"
              ref={mobileToggleRef}
              onClick={() => setMenuOpen(!menuOpen)}
              aria-label={menuOpen ? "Close menu" : "Open menu"}
              aria-expanded={menuOpen}
              aria-controls="main-navigation"
            >
              {menuOpen ? <X /> : <Menu />}
            </button>
          </div>
        </div>
      </header>

      <main id="main">
        <section className="hero" aria-labelledby="hero-heading">
          <img
            className="hero-photo"
            src={`${import.meta.env.BASE_URL}images/hero-pizza.webp`}
            alt="Golden, charred-crust pizza with melted mozzarella and fresh basil on a rustic wooden table"
            fetchPriority="high"
          />
          <div className="hero-shade" />
          <div className="container hero-inner">
            <div className="hero-content">
              <div className="eyebrow light-eyebrow">
                <span className="tiny-dot" /> YOUR LOCAL. YOUR NEXT FAVOURITE.
              </div>
              <h1 id="hero-heading">
                GOOD PIZZA.
                <br />
                <span>GREAT VIBES.</span>
              </h1>
              <p>
                A little slice of happiness, right here in Maiden Gully.
                <br className="desktop-break" /> Big flavours. Melty cheese.
                Good times guaranteed.
              </p>
              <div className="hero-buttons">
                <a href="#menu" className="button button-amber">
                  Explore the menu <ArrowUpRight size={20} />
                </a>
                <a href={PHONE} className="button button-outline">
                  <Phone size={17} /> Call & collect
                </a>
              </div>
              <a className="hero-rating" href="#reviews">
                <span className="stars" aria-label="5 stars">
                  ★★★★★
                </span>
                <strong>4.9</strong>
                <span>Loved by our locals</span>
                <ArrowRight size={15} />
              </a>
            </div>
            <div className="hero-location">
              <MapPin size={15} /> MAIDEN GULLY, VIC <span>3551</span>
            </div>
            <div className="round-stamp" aria-hidden="true">
              <svg viewBox="0 0 120 120">
                <defs>
                  <path
                    id="stamp-path"
                    d="M60,60 m-44,0 a44,44 0 1,1 88,0 a44,44 0 1,1 -88,0"
                  />
                </defs>
                <text>
                  <textPath href="#stamp-path" textLength="274">
                    LOCAL PIZZA · GOOD TIMES · SAY CHEESE ·{" "}
                  </textPath>
                </text>
              </svg>
              <Pizza size={38} strokeWidth={1.4} />
            </div>
            <a
              className="scroll-hint"
              href="#menu"
              aria-label="Scroll to our menu"
            >
              <ArrowDown size={17} />
              <span>SCROLL FOR THE GOOD STUFF</span>
            </a>
          </div>
        </section>

        <div
          className="flavour-strip"
          aria-label="Big flavour. Good company. Local love."
        >
          <div>
            BIG FLAVOUR <span>✳</span> GOOD COMPANY <span>✳</span> LOCAL LOVE{" "}
            <span>✳</span> SAY CHEESE <span>✳</span> BIG FLAVOUR <span>✳</span>{" "}
            GOOD COMPANY <span>✳</span> LOCAL LOVE <span>✳</span>
          </div>
        </div>

        <section
          className="menu-section section-pad"
          id="menu"
          aria-labelledby="menu-heading"
        >
          <div className="container">
            <div className="section-topline">
              <span className="eyebrow">01 / THE GOOD STUFF</span>
              <span className="section-note">
                <Flame size={15} /> MADE FOR YOUR NEXT PIZZA NIGHT
              </span>
            </div>
            <div className="menu-intro">
              <h2 id="menu-heading">
                HAPPINESS,
                <br />
                BY THE SLICE.
              </h2>
              <p>
                From the classics you love to your next favourite.
                <br />
                Find your pizza. Bring your people. Say cheese.
              </p>
            </div>
            <div className="menu-toolbar">
              <div className="menu-filters" aria-label="Filter pizzas">
                {["All pizzas", "Classics", "Meat lovers", "Veggie"].map(
                  (filter) => (
                    <button
                      key={filter}
                      className={
                        category === filter ? "filter active" : "filter"
                      }
                      aria-pressed={category === filter}
                      onClick={() => setCategory(filter)}
                    >
                      {filter === "Veggie" && <Leaf size={14} />} {filter}
                    </button>
                  ),
                )}
              </div>
              <span className="sample-note">
                Sample menu & prices <span>·</span> Large pizzas
              </span>
            </div>
            <div className="pizza-grid" aria-live="polite">
              {shown.map((pizza) => (
                <article className="pizza-card" key={pizza.id}>
                  <div
                    className={`pizza-photo ${pizza.image}`}
                    role="img"
                    aria-label={`${pizza.name} pizza`}
                  >
                    {pizza.tag && (
                      <span className="pizza-tag">{pizza.tag}</span>
                    )}
                    {pizza.veggie && (
                      <span className="veggie-mark" title="Vegetarian">
                        <Leaf size={15} />
                        <span className="sr-only">Vegetarian</span>
                      </span>
                    )}
                  </div>
                  <div className="pizza-details">
                    <h3>{pizza.name}</h3>
                    <p>{pizza.ingredients}</p>
                    <div className="pizza-bottom">
                      <span className="pizza-price">
                        ${pizza.price}
                        <span> / large</span>
                      </span>
                      <button
                        className="add-pizza"
                        onClick={() => addPizza(pizza)}
                        aria-label={`Add ${pizza.name} to your order`}
                      >
                        <Plus size={21} />
                      </button>
                    </div>
                  </div>
                </article>
              ))}
            </div>
            <div className="menu-bottom">
              <p>
                Good taste starts with a quick call.
                <br />
                <span>
                  Confirm today’s menu, prices & dietary options with our team.
                </span>
              </p>
              {category === "All pizzas" && (
                <button
                  className="button button-dark"
                  onClick={() => setExpanded(!expanded)}
                >
                  {expanded ? "Show our favourites" : "Explore all 12 pizzas"}
                  <ChevronDown
                    className={expanded ? "rotate-icon" : ""}
                    size={18}
                  />
                </button>
              )}
              {category !== "All pizzas" && (
                <button
                  className="text-link"
                  onClick={() => setCategory("All pizzas")}
                >
                  Back to all pizzas <ArrowRight size={18} />
                </button>
              )}
            </div>
          </div>
        </section>

        <section
          className="story-section"
          id="story"
          aria-labelledby="story-heading"
        >
          <div className="story-photo">
            <img
              src={`${import.meta.env.BASE_URL}images/hero-pizza.webp`}
              alt="A freshly baked pizza, ready to share"
              loading="lazy"
            />
            <div className="photo-caption">
              <span>LESS SCROLLING.</span>
              <span>MORE SHARING.</span>
              <ArrowUpRight size={30} />
            </div>
          </div>
          <div className="story-content">
            <span className="eyebrow light-eyebrow">
              02 / YOUR NEIGHBOURHOOD PIZZA SPOT
            </span>
            <h2>
              A LITTLE LOCAL.
              <br />A LOT TO LOVE.
            </h2>
            <p>
              There’s something about pizza that brings people together. The
              Friday-night ritual. The family catch-up. The “let’s not cook
              tonight” kind of night.
            </p>
            <p>
              That’s what Say Cheese is all about. Your local pizza stop on
              Calder Highway, serving up a reason to gather, share a slice, and
              make a good night of it.
            </p>
            <div className="story-highlights">
              <span>
                <Pizza size={23} /> Big pizza energy
              </span>
              <span>
                <Heart size={23} /> Local love
              </span>
              <span>
                <ShoppingBag size={23} /> Easy takeaway
              </span>
            </div>
            <a href="#visit" className="text-link light-link">
              Come say hello <ArrowUpRight size={18} />
            </a>
          </div>
        </section>

        <section
          className="reviews-section section-pad"
          id="reviews"
          aria-labelledby="reviews-heading"
        >
          <div className="container">
            <div className="section-topline">
              <span className="eyebrow">03 / WORD ON THE STREET</span>
              <span className="google-rating">
                <span className="google-g" aria-hidden="true">
                  G
                </span>
                <strong>4.9</strong>
                <span className="stars" aria-label="5 stars">
                  ★★★★★
                </span>
                <span>11 Google reviews</span>
              </span>
            </div>
            <div className="review-heading">
              <h2 id="reviews-heading">
                THE LOCALS
                <br />
                HAVE SPOKEN.
              </h2>
              <p>
                Good pizza gets people talking.
                <br />
                Here’s a little love from our neighbourhood.
              </p>
            </div>
            <div className="review-grid">
              {[
                [
                  "“Best in Bendigo. We go here fortnightly, never had a bad feed. Great service.”",
                  "Your new fortnightly tradition.",
                ],
                [
                  "“Definitely gained a new customer!!”",
                  "One slice is all it takes.",
                ],
                ["“And the staff are fantastic.”", "Good people. Good pizza."],
              ].map(([quote, caption]) => (
                <figure className="review-card" key={quote}>
                  <div className="review-stars" aria-label="Customer review">
                    ★★★★★<span aria-hidden="true">“</span>
                  </div>
                  <blockquote>{quote}</blockquote>
                  <figcaption>
                    <span className="review-avatar">G</span>
                    <span>
                      From our Google reviews<small>{caption}</small>
                    </span>
                    <ArrowUpRight size={16} />
                  </figcaption>
                </figure>
              ))}
            </div>
            <a
              className="text-link reviews-link"
              href="https://www.google.com/maps/search/?api=1&query=Say+Cheese+Pizza+Maiden+Gully"
              target="_blank"
              rel="noreferrer"
            >
              Read the local love on Google <ArrowUpRight size={17} />
            </a>
          </div>
        </section>

        <section className="pizza-night">
          <div className="container pizza-night-inner">
            <div>
              <span className="eyebrow">
                THE BEST PLANS ARE THE SIMPLE ONES.
              </span>
              <h2>
                YOU BRING THE PEOPLE.
                <br />
                WE’LL BRING THE PIZZA.
              </h2>
            </div>
            <a href={PHONE} className="button button-dark">
              <Phone size={18} /> Call for your next pizza night{" "}
              <ArrowUpRight size={18} />
            </a>
            <Pizza
              className="banner-pizza"
              size={155}
              strokeWidth={0.8}
              aria-hidden="true"
            />
          </div>
        </section>

        <section
          className="visit-section section-pad"
          id="visit"
          aria-labelledby="visit-heading"
        >
          <div className="container visit-grid">
            <div className="visit-content">
              <span className="eyebrow">04 / SEE YOU AT THE GULLY</span>
              <h2 id="visit-heading">
                NOT FAR.
                <br />
                SO WORTH IT.
              </h2>
              <p className="visit-intro">
                Your next pizza night starts on Calder Highway.
                <br />
                Swing by, grab your favourites, and take the good times home.
              </p>
              <div className="visit-detail">
                <MapPin size={22} />
                <div>
                  <h3>Find our little slice of town</h3>
                  <a href={MAPS} target="_blank" rel="noreferrer">
                    731 Calder Hwy
                    <br />
                    Maiden Gully VIC 3551
                  </a>
                </div>
              </div>
              <div className="visit-detail">
                <Phone size={21} />
                <div>
                  <h3>Let’s talk pizza</h3>
                  <a href={PHONE}>(03) 5406 0779</a>
                  <span>Call ahead to place your pickup order.</span>
                </div>
              </div>
              <div className="visit-detail">
                <Clock size={21} />
                <div>
                  <h3>Make it a pizza night</h3>
                  <p>Listed closing time: 10 pm</p>
                  <span>Give us a call for today’s opening hours.</span>
                </div>
              </div>
              <div className="visit-buttons">
                <a
                  className="button button-amber"
                  href={MAPS}
                  target="_blank"
                  rel="noreferrer"
                >
                  Get directions <ArrowUpRight size={18} />
                </a>
                <a className="button button-line" href={PHONE}>
                  Call the shop <Phone size={16} />
                </a>
              </div>
            </div>
            <div className="location-map">
              <div className="map-header">
                <span>
                  <span className="tiny-dot" /> A LITTLE SLICE OF MAIDEN GULLY
                </span>
                <Navigation size={17} />
              </div>
              <svg
                className="map-art"
                viewBox="0 0 550 550"
                role="img"
                aria-label="Illustrated location guide for Say Cheese Pizza on Calder Highway in Maiden Gully"
              >
                <g
                  transform={`translate(275 275) scale(${mapZoom}) translate(-275 -275)`}
                >
                  <rect width="550" height="550" fill="#e4e6d7" />
                  <path
                    d="M0 410Q120 305 140 130T290 0M500 550Q470 390 550 300"
                    fill="none"
                    stroke="#cbd4bf"
                    strokeWidth="62"
                  />
                  <path d="M-30 475L580 45" stroke="#fffdf5" strokeWidth="38" />
                  <path d="M-30 475L580 45" stroke="#d6cbb3" strokeWidth="22" />
                  <path
                    d="M-30 475L580 45"
                    stroke="#fffaf0"
                    strokeWidth="2"
                    strokeDasharray="8 10"
                  />
                  <path
                    d="M0 180L185 205L260 310L300 560M105 0L135 190M410 0L420 160L550 230M320 260L445 350L550 325M0 350L120 330"
                    fill="none"
                    stroke="#f6f4e9"
                    strokeWidth="16"
                  />
                  <path
                    d="M-20 525Q195 430 210 390T380 385T580 410"
                    stroke="#c2d5d4"
                    strokeWidth="9"
                    fill="none"
                  />
                  <g fill="#cdd7bf">
                    <rect x="32" y="48" width="77" height="65" rx="22" />
                    <rect x="322" y="80" width="58" height="49" rx="15" />
                    <rect x="398" y="442" width="84" height="65" rx="18" />
                    <rect x="45" y="360" width="48" height="53" rx="16" />
                  </g>
                  <text x="154" y="129" className="map-town">
                    MAIDEN GULLY
                  </text>
                  <text
                    x="55"
                    y="470"
                    className="map-road"
                    transform="rotate(-35 55 470)"
                  >
                    CALDER HIGHWAY
                  </text>
                  <text x="424" y="290" className="map-small">
                    TO BENDIGO →
                  </text>
                  <circle
                    cx="300"
                    cy="253"
                    r="51"
                    fill="#d97706"
                    fillOpacity=".1"
                  />
                  <circle
                    cx="300"
                    cy="253"
                    r="33"
                    fill="#d97706"
                    fillOpacity=".16"
                  />
                  <g transform="translate(279 222)">
                    <path
                      d="M21 0C9 0 0 9 0 21c0 16 21 35 21 35s21-19 21-35C42 9 33 0 21 0Z"
                      fill="#d97706"
                    />
                    <circle cx="21" cy="21" r="12" fill="#232420" />
                    <path d="M14 16q7-4 14 0l-7 15Z" fill="#f7e8c0" />
                  </g>
                </g>
              </svg>
              <div className="map-controls">
                <button
                  onClick={() =>
                    setMapZoom((zoom) => Math.min(1.6, zoom + 0.2))
                  }
                  disabled={mapZoom >= 1.6}
                  aria-label="Zoom in location illustration"
                >
                  <Plus size={19} />
                </button>
                <button
                  onClick={() => setMapZoom((zoom) => Math.max(1, zoom - 0.2))}
                  disabled={mapZoom <= 1}
                  aria-label="Zoom out location illustration"
                >
                  <span aria-hidden="true">−</span>
                </button>
              </div>
              <a
                className="map-location-card"
                href={MAPS}
                target="_blank"
                rel="noreferrer"
              >
                <span className="map-pizza-icon">
                  <Pizza size={25} />
                </span>
                <span>
                  <strong>Say Cheese Pizza</strong>
                  <small>731 Calder Hwy, Maiden Gully</small>
                </span>
                <ArrowUpRight size={22} />
              </a>
              <span className="map-caption">
                LOCATION ILLUSTRATION · OPEN MAPS FOR DIRECTIONS
              </span>
            </div>
          </div>
        </section>
      </main>

      <footer className="site-footer">
        <div className="container">
          <div className="footer-top">
            <Logo footer />
            <span className="footer-tagline">
              GOOD PIZZA. GREAT VIBES.
              <br />
              RIGHT HERE IN MAIDEN GULLY.
            </span>
            <a href={PHONE} className="footer-phone">
              (03) 5406 0779 <ArrowUpRight size={21} />
            </a>
          </div>
          <div className="footer-middle">
            <div>
              <h3>COME SAY HELLO</h3>
              <a href={MAPS} target="_blank" rel="noreferrer">
                731 Calder Hwy
                <br />
                Maiden Gully VIC 3551
              </a>
            </div>
            <div>
              <h3>THE GOOD STUFF</h3>
              <a href="#menu">Our menu</a>
              <a href="#story">Our story</a>
            </div>
            <div>
              <h3>YOUR NEXT PIZZA NIGHT</h3>
              <a href={PHONE}>Call & collect</a>
              <button onClick={openOrder}>
                Your order {count > 0 ? `(${count})` : ""}
              </button>
            </div>
            <div>
              <h3>A LITTLE LOCAL LOVE</h3>
              <a href="#reviews">What the locals say</a>
              <a href={MAPS} target="_blank" rel="noreferrer">
                Find us on Google <ArrowUpRight size={12} />
              </a>
            </div>
          </div>
          <div className="footer-big-type" aria-hidden="true">
            SAY CHEESE<span>☺</span>
          </div>
          <div className="footer-bottom">
            <span>
              © {new Date().getFullYear()} Say Cheese Pizza Maiden Gully
            </span>
            <span>Made for good food & good company.</span>
            <a href="#home">
              Back to top <ArrowUpRight size={13} />
            </a>
          </div>
        </div>
      </footer>
      {count > 0 && (
        <button
          className="floating-order"
          hidden={cartOpen}
          onClick={openOrder}
        >
          <ShoppingBag size={18} />
          <span>Your order</span>
          <strong>{count}</strong>
          <ArrowRight size={16} />
        </button>
      )}
      <div
        className={toast ? "toast visible" : "toast"}
        role="status"
        aria-live="polite"
      >
        <Check size={17} />
        {toast}
      </div>
      <OrderDrawer
        open={cartOpen}
        onClose={() => setCartOpen(false)}
        items={items}
        onQuantityChange={changeQuantity}
        onRemove={(id) =>
          setItems((current) => current.filter((item) => item.id !== id))
        }
        onClear={() => setItems([])}
        returnFocusRef={orderOpenerRef}
        fallbackFocusRef={bagButtonRef}
      />
    </>
  );
}

export default App;
