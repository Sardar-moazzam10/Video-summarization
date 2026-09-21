import React, { useEffect, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import "./AdminPanelStyles.css";
import { API_BASE_URL } from "../config/api.js";

const sidebarLinks = [
  { path: "/admin-account-info", label: "Account Info", icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg> },
  { path: "/admin-security", label: "Security", icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg> },
  { path: "/admin-history", label: "History", icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg> },
  { path: "/admin-stats", label: "Platform Stats", icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg> },
  { path: "/admin-users", label: "Manage Users", icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg> },
];

const authHeaders = () => ({
  "Content-Type": "application/json",
  "Authorization": `Bearer ${localStorage.getItem("access_token") || ""}`,
});

const AdminUserListPage = () => {
  const [users, setUsers] = useState([]);
  const [search, setSearch] = useState("");
  const [message, setMessage] = useState("");
  const [msgType, setMsgType] = useState("success");
  const [showAddForm, setShowAddForm] = useState(false);
  const [userData, setUserData] = useState({});
  const [confirmDeleteUsername, setConfirmDeleteUsername] = useState(null);
  const [newUser, setNewUser] = useState({
    firstName: "", lastName: "", username: "", email: "", password: "", role: "user"
  });
  const navigate = useNavigate();
  const location = useLocation();
  const currentUsername = JSON.parse(localStorage.getItem("user"))?.username;

  useEffect(() => {
    fetchUsers();
    if (currentUsername) {
      fetch(`${API_BASE_URL}/api/v1/auth/user/${currentUsername}`, { headers: authHeaders() })
        .then(r => r.json())
        .then(d => setUserData(d))
        .catch(() => {});
    }
  }, [currentUsername]);

  const fetchUsers = () => {
    fetch(`${API_BASE_URL}/api/v1/auth/users`, { headers: authHeaders() })
      .then(async (res) => {
        if (res.status === 401 || res.status === 403) {
          setMessage("Admin access required.");
          setMsgType("error");
          return [];
        }
        return res.json();
      })
      .then(data => {
        if (Array.isArray(data)) {
          setUsers(data.map(user => ({ ...user, originalUsername: user.username })));
        }
      })
      .catch(() => {
        setMessage("Failed to fetch users from server.");
        setMsgType("error");
      });
  };

  const handleInputChange = (index, field, value) => {
    const updated = [...users];
    updated[index][field] = value;
    setUsers(updated);
  };

  const handleUpdate = (user) => {
    fetch(`${API_BASE_URL}/api/v1/auth/admin/user/${user.originalUsername}`, {
      method: "PUT",
      headers: authHeaders(),
      body: JSON.stringify({
        firstName: user.firstName,
        lastName: user.lastName,
        username: user.username,
        email: user.email,
        role: user.role,
        isActive: user.isActive !== false,
      })
    })
      .then(async (res) => {
        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.detail || data.message || "Update failed");
        }
        return data;
      })
      .then(data => {
        setMessage(data.message || "User updated successfully");
        setMsgType("success");
        const current = JSON.parse(localStorage.getItem("user"));
        if (current?.username === user.originalUsername) {
          current.username = data.newUsername || user.username;
          current.email = user.email;
          current.firstName = user.firstName;
          current.role = user.role;
          localStorage.setItem("user", JSON.stringify(current));
        }
        fetchUsers();
      })
      .catch((err) => {
        setMessage(err.message || "Update failed.");
        setMsgType("error");
        fetchUsers();
      });
  };

  const handleDelete = (user) => {
    if (user.role === "admin") {
      setMessage("Cannot delete an admin account. First change the admin role to user.");
      setMsgType("error");
      return;
    }
    setConfirmDeleteUsername(user.username);
  };

  const handleConfirmDelete = () => {
    const target = confirmDeleteUsername;
    setConfirmDeleteUsername(null);
    fetch(`${API_BASE_URL}/api/v1/auth/user/delete/${target}`, {
      method: "DELETE",
      headers: authHeaders()
    })
      .then(async (res) => {
        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.detail || data.message || "Delete failed");
        }
        return data;
      })
      .then(data => {
        setMessage(data.message || "User deleted successfully.");
        setMsgType("success");
        fetchUsers();
      })
      .catch((err) => {
        setMessage(err.message || "Error occurred while deleting user.");
        setMsgType("error");
      });
  };

  const handleToggleStatus = (user) => {
    if (user.role === "admin") {
      setMessage("Cannot deactivate an admin account. First change the admin role to user.");
      setMsgType("error");
      return;
    }
    if (user.username === currentUsername) {
      setMessage("Cannot deactivate your own account.");
      setMsgType("error");
      return;
    }

    fetch(`${API_BASE_URL}/api/v1/auth/admin/toggle-user/${user.username}`, {
      method: "PATCH",
      headers: authHeaders(),
    })
      .then(async (res) => {
        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.detail || data.message || "Toggle failed");
        }
        return data;
      })
      .then(data => {
        setMessage(data.message || `User ${data.isActive ? "activated" : "deactivated"} successfully.`);
        setMsgType("success");
        fetchUsers();
      })
      .catch((err) => {
        setMessage(err.message || "Error toggling user status.");
        setMsgType("error");
      });
  };

  const handleAddUser = () => {
    const { firstName, lastName, username, email, password, role } = newUser;
    if (!firstName || !lastName || !username || !email || !password || !role) {
      setMessage("Please fill out all fields.");
      setMsgType("error");
      return;
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      setMessage("Please enter a valid email address.");
      setMsgType("error");
      return;
    }
    if (password.length < 6) {
      setMessage("Password must be at least 6 characters.");
      setMsgType("error");
      return;
    }

    fetch(`${API_BASE_URL}/api/v1/auth/admin/create-user`, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify(newUser)
    })
      .then(async (res) => {
        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.detail || data.message || "Failed to create user");
        }
        return data;
      })
      .then(data => {
        setMessage(data.message || "User created successfully");
        setMsgType("success");
        setNewUser({ firstName: "", lastName: "", username: "", email: "", password: "", role: "user" });
        setShowAddForm(false);
        fetchUsers();
      })
      .catch((err) => {
        setMessage(err.message || "Failed to create user.");
        setMsgType("error");
      });
  };

  const filteredUsers = users.filter(u =>
    u.username?.toLowerCase().includes(search.toLowerCase()) ||
    u.email?.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="admin-page">
      <div className="admin-bg-gradient" />

      <div className="admin-layout">
        <aside className="admin-sidebar">
          <div className="admin-sidebar-header">
            <div className="admin-sidebar-avatar">
              {(userData.firstName || "A").charAt(0).toUpperCase()}
            </div>
            <div className="admin-sidebar-info">
              <p className="admin-sidebar-name">{userData.firstName} {userData.lastName}</p>
              <p className="admin-sidebar-role">Admin</p>
            </div>
          </div>

          <nav className="admin-sidebar-nav">
            {sidebarLinks.map((link) => (
              <button
                key={link.path}
                className={`admin-sidebar-link ${location.pathname === link.path ? "admin-sidebar-link-active" : ""}`}
                onClick={() => navigate(link.path)}
              >
                {link.icon}
                {link.label}
              </button>
            ))}
          </nav>
        </aside>

        <main className="admin-main admin-main-wide">
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3 }}
          >
            <h1 className="admin-heading">Manage Users</h1>
            <p className="admin-subheading">View, edit, activate/deactivate, and manage platform users</p>

            <div style={{ display: "flex", gap: "12px", marginBottom: "20px", flexWrap: "wrap" }}>
              <div style={{ flex: 1, minWidth: "200px" }}>
                <input
                  className="admin-input"
                  type="text"
                  placeholder="Search by username or email..."
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>
              <button
                className={showAddForm ? "admin-btn-secondary" : "admin-btn-primary"}
                onClick={() => setShowAddForm(!showAddForm)}
              >
                {showAddForm ? "Cancel" : "Add New User"}
              </button>
            </div>

            <AnimatePresence>
              {showAddForm && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  exit={{ opacity: 0, height: 0 }}
                  style={{ overflow: "hidden" }}
                >
                  <div className="admin-card" style={{ marginBottom: "20px" }}>
                    <h3 style={{ fontSize: "1rem", fontWeight: 700, color: "#fff", margin: "0 0 20px" }}>Add New User</h3>
                    <div className="admin-form-grid">
                      <div className="admin-field">
                        <label className="admin-label">First Name</label>
                        <input className="admin-input" placeholder="First Name" value={newUser.firstName} onChange={(e) => setNewUser({ ...newUser, firstName: e.target.value })} />
                      </div>
                      <div className="admin-field">
                        <label className="admin-label">Last Name</label>
                        <input className="admin-input" placeholder="Last Name" value={newUser.lastName} onChange={(e) => setNewUser({ ...newUser, lastName: e.target.value })} />
                      </div>
                      <div className="admin-field">
                        <label className="admin-label">Username</label>
                        <input className="admin-input" placeholder="Username" value={newUser.username} onChange={(e) => setNewUser({ ...newUser, username: e.target.value })} />
                      </div>
                      <div className="admin-field">
                        <label className="admin-label">Email</label>
                        <input className="admin-input" placeholder="Email" value={newUser.email} onChange={(e) => setNewUser({ ...newUser, email: e.target.value })} />
                      </div>
                      <div className="admin-field">
                        <label className="admin-label">Password</label>
                        <input className="admin-input" type="password" placeholder="Password (min 6 chars)" value={newUser.password} onChange={(e) => setNewUser({ ...newUser, password: e.target.value })} />
                      </div>
                      <div className="admin-field">
                        <label className="admin-label">Role</label>
                        <select className="admin-select" value={newUser.role} onChange={(e) => setNewUser({ ...newUser, role: e.target.value })}>
                          <option value="user">User</option>
                          <option value="admin">Admin</option>
                        </select>
                      </div>
                    </div>
                    <button className="admin-btn-primary" onClick={handleAddUser}>Create User</button>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            {message && (
              <div className={`admin-message ${msgType === "error" ? "admin-message-error" : "admin-message-success"}`} style={{ marginBottom: "16px", marginTop: 0 }}>
                {message}
              </div>
            )}

            <AnimatePresence>
              {confirmDeleteUsername && (
                <motion.div
                  initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}
                  style={{
                    display: "flex", alignItems: "center", gap: "12px", flexWrap: "wrap",
                    padding: "14px 18px", marginBottom: "16px",
                    background: "rgba(239,68,68,0.08)",
                    border: "1px solid rgba(239,68,68,0.2)",
                    borderRadius: "12px",
                  }}
                >
                  <span style={{ fontSize: "13.5px", color: "rgba(255,255,255,0.7)", flex: 1 }}>
                    Delete user <strong style={{ color: "#fff" }}>{confirmDeleteUsername}</strong>? This cannot be undone.
                  </span>
                  <button className="admin-btn-danger admin-btn-sm" onClick={handleConfirmDelete}>Confirm Delete</button>
                  <button className="admin-btn-secondary admin-btn-sm" onClick={() => setConfirmDeleteUsername(null)}>Cancel</button>
                </motion.div>
              )}
            </AnimatePresence>

            <div className="admin-table-wrap">
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>First Name</th>
                    <th>Last Name</th>
                    <th>Username</th>
                    <th>Email</th>
                    <th style={{ width: "110px" }}>Role</th>
                    <th style={{ textAlign: "center", width: "90px" }}>Status</th>
                    <th style={{ textAlign: "center", width: "230px" }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredUsers.map((user, index) => (
                    <tr key={user.originalUsername || index}>
                      <td>
                        <input className="admin-table-input" value={user.firstName || ""} onChange={(e) => handleInputChange(index, "firstName", e.target.value)} />
                      </td>
                      <td>
                        <input className="admin-table-input" value={user.lastName || ""} onChange={(e) => handleInputChange(index, "lastName", e.target.value)} />
                      </td>
                      <td>
                        <input className="admin-table-input" value={user.username || ""} onChange={(e) => handleInputChange(index, "username", e.target.value)} />
                      </td>
                      <td>
                        <input className="admin-table-input" value={user.email || ""} onChange={(e) => handleInputChange(index, "email", e.target.value)} />
                      </td>
                      <td>
                        <select
                          className="admin-table-select"
                          style={{ width: "100%" }}
                          value={user.role || "user"}
                          onChange={(e) => handleInputChange(index, "role", e.target.value)}
                        >
                          <option value="user">User</option>
                          <option value="admin">Admin</option>
                        </select>
                      </td>
                      <td style={{ textAlign: "center" }}>
                        <span style={{
                          display: "inline-block",
                          padding: "4px 10px",
                          borderRadius: "20px",
                          fontSize: "11.5px",
                          fontWeight: 600,
                          background: user.isActive === false ? "rgba(239,68,68,0.12)" : "rgba(52,211,153,0.12)",
                          color: user.isActive === false ? "#f87171" : "#34d399",
                          border: `1px solid ${user.isActive === false ? "rgba(239,68,68,0.2)" : "rgba(52,211,153,0.2)"}`,
                        }}>
                          {user.isActive === false ? "Inactive" : "Active"}
                        </span>
                      </td>
                      <td style={{ textAlign: "center", whiteSpace: "nowrap" }}>
                        <div style={{ display: "inline-flex", gap: "8px", alignItems: "center" }}>
                          <button
                            className="admin-btn-primary admin-btn-sm"
                            onClick={() => handleUpdate(user)}
                            title="Save changes"
                          >
                            Save
                          </button>
                          <button
                            className="admin-btn-sm"
                            style={{
                              background: user.isActive === false ? "rgba(52,211,153,0.15)" : "rgba(251,191,36,0.12)",
                              color: user.isActive === false ? "#34d399" : "#fbbf24",
                              border: `1px solid ${user.isActive === false ? "rgba(52,211,153,0.25)" : "rgba(251,191,36,0.25)"}`,
                              borderRadius: "8px",
                              padding: "5px 10px",
                              cursor: "pointer",
                              fontSize: "12px",
                              fontWeight: 600,
                            }}
                            onClick={() => handleToggleStatus(user)}
                            title={user.isActive === false ? "Activate user" : "Deactivate user"}
                          >
                            {user.isActive === false ? "Activate" : "Deactivate"}
                          </button>
                          <button
                            className="admin-btn-danger admin-btn-sm"
                            onClick={() => handleDelete(user)}
                            title="Delete user"
                          >
                            Delete
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {filteredUsers.length === 0 && (
                    <tr>
                      <td colSpan="7" style={{ textAlign: "center", padding: "32px", color: "rgba(255,255,255,0.35)" }}>
                        No users found.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </motion.div>
        </main>
      </div>
    </div>
  );
};

export default AdminUserListPage;
