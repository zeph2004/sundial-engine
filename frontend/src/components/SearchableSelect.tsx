import React, { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, Search, X } from "lucide-react";
import type { EntityOption } from "../api/client";

interface SearchableSelectProps {
  options: EntityOption[];
  value: string;
  onChange: (id: string) => void;
  placeholder?: string;
  ariaLabel?: string;
}

export const SearchableSelect: React.FC<SearchableSelectProps> = ({
  options,
  value,
  onChange,
  placeholder = "Search...",
  ariaLabel = "Select entity",
}) => {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [highlightIdx, setHighlightIdx] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const selectedOption = useMemo(
    () => options.find((o) => o.id === value) ?? null,
    [options, value]
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return options;
    return options.filter(
      (o) =>
        o.id.toLowerCase().includes(q) || o.label.toLowerCase().includes(q)
    );
  }, [options, query]);

  useEffect(() => {
    setHighlightIdx(0);
  }, [query, open]);

  useEffect(() => {
    const handleOutside = (e: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handleOutside);
    return () => document.removeEventListener("mousedown", handleOutside);
  }, []);

  const commitSelection = (opt: EntityOption) => {
    onChange(opt.id);
    setQuery("");
    setOpen(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!open && (e.key === "ArrowDown" || e.key === "Enter")) {
      setOpen(true);
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlightIdx((prev) =>
        filtered.length > 0 ? (prev + 1) % filtered.length : 0
      );
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlightIdx((prev) =>
        filtered.length > 0 ? (prev - 1 + filtered.length) % filtered.length : 0
      );
    } else if (e.key === "Enter" && filtered[highlightIdx]) {
      e.preventDefault();
      commitSelection(filtered[highlightIdx]);
    } else if (e.key === "Escape") {
      setOpen(false);
      setQuery("");
    }
  };

  return (
    <div className="sd-select" ref={containerRef}>
      <div
        className={`sd-select-control ${open ? "is-open" : ""}`}
        onClick={() => {
          setOpen(true);
          setTimeout(() => inputRef.current?.focus(), 0);
        }}
      >
        <Search size={16} className="sd-select-icon" aria-hidden="true" />
        <input
          ref={inputRef}
          type="text"
          className="sd-select-input"
          aria-label={ariaLabel}
          role="combobox"
          aria-expanded={open}
          value={open ? query : selectedOption ? selectedOption.label : ""}
          placeholder={selectedOption ? selectedOption.label : placeholder}
          onFocus={() => setOpen(true)}
          onChange={(e) => {
            setQuery(e.target.value);
            if (!open) setOpen(true);
          }}
          onKeyDown={handleKeyDown}
        />
        {open && query && (
          <button
            type="button"
            className="sd-select-clear"
            aria-label="Clear search"
            onClick={(e) => {
              e.stopPropagation();
              setQuery("");
              inputRef.current?.focus();
            }}
          >
            <X size={14} />
          </button>
        )}
        <ChevronDown size={16} className="sd-select-chevron" aria-hidden="true" />
      </div>

      {open && (
        <ul className="sd-select-menu" role="listbox">
          {filtered.length === 0 ? (
            <li className="sd-select-empty">No matching entries found.</li>
          ) : (
            filtered.slice(0, 80).map((opt, idx) => {
              const isSelected = opt.id === value;
              const isHighlighted = idx === highlightIdx;
              return (
                <li
                  key={opt.id}
                  role="option"
                  aria-selected={isSelected}
                  className={`sd-select-option ${isSelected ? "is-selected" : ""} ${
                    isHighlighted ? "is-highlighted" : ""
                  }`}
                  onMouseEnter={() => setHighlightIdx(idx)}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    commitSelection(opt);
                  }}
                >
                  <span className="sd-select-option-label">{opt.label}</span>
                  <span className="sd-select-option-id">{opt.id}</span>
                </li>
              );
            })
          )}
        </ul>
      )}
    </div>
  );
};
