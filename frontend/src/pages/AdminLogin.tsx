import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowLeft, Lock } from "lucide-react";
import { ApiError, loginAdmin } from "../api/client";
import { SundialMark } from "../components/SundialMark";

export const AdminLogin: React.FC = () => {
  const navigate = useNavigate();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await loginAdmin(username.trim(), password);
      navigate("/studio", { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError("Incorrect username or password. Please try again.");
      } else {
        setError(
          err instanceof Error
            ? err.message
            : "Could not reach the authentication server."
        );
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="auth-shell">
      <div className="auth-card">
        <div className="auth-brand">
          <SundialMark size={28} />
          <div>
            <div className="auth-wordmark">sundial</div>
            <div className="auth-tagline">Time, worked out.</div>
          </div>
        </div>

        <h1 className="auth-heading">Registrar sign in</h1>
        <p className="auth-sub">
          Sign in to manage timetable data, rules, and solver runs.
        </p>

        {error && (
          <div className="inline-alert alert-clash" role="alert">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="auth-form">
          <label className="field-label">
            <span>Username</span>
            <input
              type="text"
              className="field-input"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              required
            />
          </label>

          <label className="field-label">
            <span>Password</span>
            <input
              type="password"
              className="field-input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </label>

          <button
            type="submit"
            className="btn btn-primary btn-full"
            disabled={submitting}
          >
            <Lock size={15} />
            <span>{submitting ? "Signing in..." : "Sign in"}</span>
          </button>
        </form>

        <div className="auth-footer">
          <Link to="/" className="text-link">
            <ArrowLeft size={14} />
            <span>Back to public timetable</span>
          </Link>
        </div>
      </div>
    </div>
  );
};
