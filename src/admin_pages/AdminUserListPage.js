import React, { useEffect, useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import './AdminPanelStyles.css';

const sidebarLinks = [
  { path: '/admin-account-info', label: 'Account Info', icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg> },
  { path: '/admin-security', label: 'Security', icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg> },
  { path: '/admin-history', label: 'History', icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg> },
  { path: '/admin-users', label: 'Manage Users', icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg> },
];

const AdminUserListPage = () => {
  const [users, setUsers] = useState([]);
  const [search, setSearch] = useState('');
  const [message, setMessage] = useState('');
  const [msgType, setMsgType] = useState('success');
  const [showAddForm, setShowAddForm] = useState(false);
  const [userData, setUserData] = useState({});
  const [newUser, setNewUser] = useState({
    firstName: '', lastName: '', username: '', email: '', password: '', role: 'user'
  });
  const navigate = useNavigate();
  const location = useLocation();
  const currentUsername = JSON.parse(localStorage.getItem('user'))?.username;

  useEffect(() => {
    fetchUsers();
    if (currentUsername) {
      fetch(`http://localhost:8000/api/v1/auth/user/${currentUsername}`)
        .then(r => r.json()).then(d => setUserData(d)).catch(() => {});
    }
  }, [currentUsername]);

  const fetchUsers = () => {
    fetch('http://localhost:8000/api/v1/auth/users')
      .then(res => res.json())
      .then(data => {
        setUsers(data.map(user => ({ ...user, originalUsername: user.username })));
      })
      .catch(() => { setMessage('Failed to fetch users.'); setMsgType('error'); });
  };

  const handleInputChange = (index, field, value) => {
    const updated = [...users];
    updated[index][field] = value;
    setUsers(updated);
  };

  const handleUpdate = (user) => {
    fetch(`http://localhost:8000/api/v1/auth/user/update/${user.originalUsername}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(user)
    })
      .then(res => res.json())
      .then(data => {
        setMessage(data.message || 'User updated');
        setMsgType('success');
        const current = JSON.parse(localStorage.getItem('user'));
        if (current?.username === user.originalUsername) {
          current.username = data.newUsername || user.username;
          current.email = user.email;
          current.firstName = user.firstName;
          current.role = user.role;
          localStorage.setItem('user', JSON.stringify(current));
        }
        fetchUsers();
      })
      .catch(() => { setMessage('Update failed.'); setMsgType('error'); });
  };

  const handleDelete = (username) => {
    if (window.confirm(`Delete user '${username}'?`)) {
      fetch(`http://localhost:8000/api/v1/auth/user/delete/${username}`, { method: 'DELETE' })
        .then(res => res.json())
        .then(data => {
          setMessage(data.success ? 'User deleted.' : 'Delete failed.');
          setMsgType(data.success ? 'success' : 'error');
          fetchUsers();
        })
        .catch(() => { setMessage('Error occurred.'); setMsgType('error'); });
    }
  };

  const handleAddUser = () => {
    const { firstName, lastName, username, email, password, role } = newUser;
    if (!firstName || !lastName || !username || !email || !password || !role) {
      setMessage('Please fill out all fields.'); setMsgType('error'); return;
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      setMessage('Please enter a valid email.'); setMsgType('error'); return;
    }
    if (password.length < 6) {
      setMessage('Password must be at least 6 characters.'); setMsgType('error'); return;
    }

    fetch('http://localhost:8000/api/v1/auth/signup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(newUser)
    })
      .then(res => res.json())
      .then(data => {
        setMessage(data.message || 'User created');
        setMsgType(data.success ? 'success' : 'error');
        if (data.success) {
          setNewUser({ firstName: '', lastName: '', username: '', email: '', password: '', role: 'user' });
          setShowAddForm(false);
          fetchUsers();
        }
      })
      .catch(() => { setMessage('Failed to create user.'); setMsgType('error'); });
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
              {(userData.firstName || 'A').charAt(0).toUpperCase()}
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
                className={`admin-sidebar-link ${location.pathname === link.path ? 'admin-sidebar-link-active' : ''}`}
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
            <p className="admin-subheading">View, edit, and manage all registered users</p>

            <div style={{ display: 'flex', gap: '12px', marginBottom: '20px', flexWrap: 'wrap' }}>
              <div style={{ flex: 1, minWidth: '200px' }}>
                <input
                  className="admin-input"
                  type="text"
                  placeholder="Search by username or email..."
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>
              <button
                className={showAddForm ? 'admin-btn-secondary' : 'admin-btn-primary'}
                onClick={() => setShowAddForm(!showAddForm)}
              >
                {showAddForm ? 'Cancel' : 'Add New User'}
              </button>
            </div>

            <AnimatePresence>
              {showAddForm && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  style={{ overflow: 'hidden' }}
                >
                  <div className="admin-card" style={{ marginBottom: '20px' }}>
                    <h3 style={{ fontSize: '1rem', fontWeight: 700, color: '#fff', margin: '0 0 20px' }}>Add New User</h3>
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
                        <input className="admin-input" type="password" placeholder="Password" value={newUser.password} onChange={(e) => setNewUser({ ...newUser, password: e.target.value })} />
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
              <div className={`admin-message ${msgType === 'error' ? 'admin-message-error' : 'admin-message-success'}`} style={{ marginBottom: '16px', marginTop: 0 }}>
                {message}
              </div>
            )}

            <div className="admin-table-wrap">
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>First Name</th>
                    <th>Last Name</th>
                    <th>Username</th>
                    <th>Email</th>
                    <th>Role</th>
                    <th style={{ textAlign: 'center' }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredUsers.map((user, index) => (
                    <tr key={index}>
                      <td>
                        <input className="admin-table-input" value={user.firstName || ''} onChange={(e) => handleInputChange(index, 'firstName', e.target.value)} />
                      </td>
                      <td>
                        <input className="admin-table-input" value={user.lastName || ''} onChange={(e) => handleInputChange(index, 'lastName', e.target.value)} />
                      </td>
                      <td>
                        <input className="admin-table-input" value={user.username || ''} onChange={(e) => handleInputChange(index, 'username', e.target.value)} />
                      </td>
                      <td>
                        <input className="admin-table-input" value={user.email || ''} onChange={(e) => handleInputChange(index, 'email', e.target.value)} />
                      </td>
                      <td>
                        <select className="admin-table-select" value={user.role || ''} onChange={(e) => handleInputChange(index, 'role', e.target.value)}>
                          <option value="user">User</option>
                          <option value="admin">Admin</option>
                        </select>
                      </td>
                      <td>
                        <div style={{ display: 'flex', gap: '8px', justifyContent: 'center' }}>
                          <button className="admin-btn-primary admin-btn-sm" onClick={() => handleUpdate(user)}>
                            Save
                          </button>
                          <button className="admin-btn-danger admin-btn-sm" onClick={() => handleDelete(user.username)}>
                            Delete
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {filteredUsers.length === 0 && (
                    <tr>
                      <td colSpan="6" style={{ textAlign: 'center', padding: '32px', color: 'rgba(255,255,255,0.35)' }}>
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
