import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  ArrowRight,
  Check,
  Copy,
  Minus,
  Phone,
  Plus,
  ShoppingBag,
  Trash2,
  X,
} from "lucide-react";
import "./OrderDrawer.css";

const currency = new Intl.NumberFormat("en-AU", {
  style: "currency",
  currency: "AUD",
});
const focusableSelector =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

export default function OrderDrawer({
  open,
  onClose,
  items = [],
  onQuantityChange,
  onRemove,
  onClear,
  returnFocusRef,
  fallbackFocusRef,
}) {
  const headingId = useId();
  const noteId = useId();
  const dialogRef = useRef(null);
  const closeRef = useRef(null);
  const fallbackRef = useRef(null);
  const [copyState, setCopyState] = useState("idle");
  const [fallbackText, setFallbackText] = useState("");
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  const itemCount = items.reduce((count, item) => count + item.quantity, 0);
  const total = items.reduce(
    (amount, item) => amount + item.price * item.quantity,
    0,
  );

  useEffect(() => {
    if (!open) return undefined;

    const previousFocus = returnFocusRef?.current || document.activeElement;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    setCopyState("idle");
    setFallbackText("");
    const frame = requestAnimationFrame(() => closeRef.current?.focus());

    const handleKeyDown = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current?.();
        return;
      }
      if (event.key !== "Tab") return;

      const focusable = Array.from(
        dialogRef.current?.querySelectorAll(focusableSelector) || [],
      ).filter((element) => element.getClientRects().length > 0);
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!first) {
        event.preventDefault();
        dialogRef.current?.focus();
      } else if (
        event.shiftKey &&
        (document.activeElement === first ||
          !dialogRef.current?.contains(document.activeElement))
      ) {
        event.preventDefault();
        last.focus();
      } else if (
        !event.shiftKey &&
        (document.activeElement === last ||
          !dialogRef.current?.contains(document.activeElement))
      ) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousOverflow;
      if (
        previousFocus instanceof HTMLElement &&
        previousFocus.isConnected &&
        previousFocus.getClientRects().length > 0
      )
        previousFocus.focus();
      else fallbackFocusRef?.current?.focus();
    };
  }, [open, returnFocusRef, fallbackFocusRef]);

  useEffect(() => {
    if (open && fallbackText) {
      fallbackRef.current?.focus();
      fallbackRef.current?.select();
    }
  }, [open, fallbackText]);

  useEffect(() => {
    setCopyState("idle");
    setFallbackText("");
  }, [items]);

  const copyOrder = async () => {
    const orderText = [
      "Say Cheese Pizza — my order",
      ...items.map(
        (item) =>
          `${item.quantity} × ${item.name} — ${currency.format(item.price * item.quantity)}`,
      ),
      "",
      `Menu estimate: ${currency.format(total)} AUD`,
      "Menu preview — confirm current prices and availability by phone.",
      "Call Say Cheese Pizza: (03) 5406 0779",
    ].join("\n");

    try {
      if (!navigator.clipboard?.writeText)
        throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(orderText);
      setCopyState("copied");
      setFallbackText("");
    } catch {
      setCopyState("fallback");
      setFallbackText(orderText);
    }
  };

  if (!open || typeof document === "undefined") return null;

  return createPortal(
    <div
      className="order-overlay"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose?.();
      }}
    >
      <section
        className="order-drawer"
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={headingId}
        aria-describedby={noteId}
        tabIndex={-1}
      >
        <header className="order-header">
          <div>
            <p className="order-eyebrow">GOOD TIMES. GREAT PIZZA.</p>
            <h2 id={headingId}>
              Your order
              <span className="order-count" aria-label={`${itemCount} items`}>
                {itemCount}
              </span>
            </h2>
          </div>
          <button
            ref={closeRef}
            className="order-icon-button order-close"
            type="button"
            onClick={onClose}
            aria-label="Close your order"
          >
            <X size={23} aria-hidden="true" />
          </button>
        </header>

        <div className="order-content">
          {items.length ? (
            <>
              <div className="order-list-heading">
                <span>
                  {itemCount} {itemCount === 1 ? "item" : "items"} on your list
                </span>
                <button type="button" className="order-clear" onClick={onClear}>
                  Clear all
                </button>
              </div>
              <ul className="order-list">
                {items.map((item) => (
                  <li className="order-item" key={item.id}>
                    <div className="order-item-top">
                      <div>
                        <h3>{item.name}</h3>
                        <p>{currency.format(item.price)} each</p>
                      </div>
                      <button
                        className="order-icon-button order-remove"
                        type="button"
                        onClick={() => onRemove?.(item.id)}
                        aria-label={`Remove ${item.name}`}
                      >
                        <Trash2 size={18} aria-hidden="true" />
                      </button>
                    </div>
                    <div className="order-item-bottom">
                      <div
                        className="order-quantity"
                        aria-label={`Quantity for ${item.name}`}
                      >
                        <button
                          type="button"
                          onClick={() =>
                            onQuantityChange?.(item.id, item.quantity - 1)
                          }
                          disabled={item.quantity <= 1}
                          aria-label={`Decrease quantity of ${item.name}`}
                        >
                          <Minus size={16} aria-hidden="true" />
                        </button>
                        <span
                          aria-live="polite"
                          aria-label={`${item.quantity} ${item.name}`}
                        >
                          {item.quantity}
                        </span>
                        <button
                          type="button"
                          onClick={() =>
                            onQuantityChange?.(item.id, item.quantity + 1)
                          }
                          disabled={item.quantity >= 20}
                          aria-label={`Increase quantity of ${item.name}`}
                        >
                          <Plus size={16} aria-hidden="true" />
                        </button>
                      </div>
                      <span className="order-item-price">
                        {currency.format(item.price * item.quantity)}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
              <div className="order-phone-hint">
                <Phone size={18} aria-hidden="true" />
                <p>
                  Build your list, then give us a call. We’ll take care of the
                  pizza.
                </p>
              </div>
            </>
          ) : (
            <div className="order-empty">
              <div className="order-empty-icon">
                <ShoppingBag size={44} strokeWidth={1.4} aria-hidden="true" />
              </div>
              <p className="order-eyebrow">LET’S GET YOU FED</p>
              <h3>
                A little empty
                <br />
                in here.
              </h3>
              <p>
                Find your favourites on the menu and add them to your order
                list.
              </p>
              <button
                className="order-browse"
                type="button"
                onClick={() => {
                  onClose?.();
                  requestAnimationFrame(() =>
                    document.getElementById("menu")?.scrollIntoView(),
                  );
                }}
              >
                Browse the menu <ArrowRight size={19} aria-hidden="true" />
              </button>
            </div>
          )}
        </div>

        <footer className="order-footer">
          {!!items.length && (
            <>
              <div className="order-total">
                <div>
                  <span>Estimated total</span>
                  <small>Prices in AUD</small>
                </div>
                <strong>{currency.format(total)}</strong>
              </div>
              <a className="order-call" href="tel:+61354060779">
                <Phone size={19} aria-hidden="true" />
                Call to place your order
                <ArrowRight size={19} aria-hidden="true" />
              </a>
              <button className="order-copy" type="button" onClick={copyOrder}>
                {copyState === "copied" ? (
                  <Check size={18} aria-hidden="true" />
                ) : (
                  <Copy size={18} aria-hidden="true" />
                )}
                {copyState === "copied"
                  ? "Order list copied"
                  : "Copy your order list"}
              </button>
              <div
                className="order-copy-status"
                role="status"
                aria-live="polite"
              >
                {copyState === "copied" &&
                  "Copied. Your list is ready to share."}
                {copyState === "fallback" &&
                  "Copy the selected order list below."}
              </div>
              {fallbackText && (
                <textarea
                  ref={fallbackRef}
                  className="order-copy-fallback"
                  aria-label="Your order list to copy"
                  value={fallbackText}
                  readOnly
                  rows={5}
                />
              )}
            </>
          )}
          <p id={noteId} className="order-note">
            Menu preview — confirm current prices and availability by phone.
          </p>
        </footer>
      </section>
    </div>,
    document.body,
  );
}
