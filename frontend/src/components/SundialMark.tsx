import React from "react";

interface SundialMarkProps {
  size?: number;
  variant?: "default" | "on-dark";
}

/**
 * Sundial symbol (Direction A — heavy, plain dial with centred gnomon and 30-degree shadow wedge).
 * Follows sundial-brand-guideline.md Section 6: at most two colours (Shadow + Noon), no gradients or drop shadows.
 */
export const SundialMark: React.FC<SundialMarkProps> = ({
  size = 24,
  variant = "default",
}) => {
  const stroke = variant === "on-dark" ? "#F4F1EA" : "#11151C";
  const gnomon = variant === "on-dark" ? "#F4F1EA" : "#11151C";
  const noon = "#F2A71B";

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
      style={{ display: "block", flexShrink: 0 }}
    >
      <circle cx="16" cy="16" r="13.5" stroke={stroke} strokeWidth="2.5" />
      {/* 30-degree shadow wedge from centre */}
      <path d="M16 16 L16 28.5 A12.5 12.5 0 0 0 26.8 22.25 Z" fill={noon} />
      {/* Centred straight-edged gnomon */}
      <rect x="14.5" y="4.5" width="3" height="12.5" fill={gnomon} />
    </svg>
  );
};
