import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import '../admin_pages/AdminPanelStyles.css';

const AdminUserListPage = () => {
  const [users, setUsers] = useState([]);
  const [search, setSearch] = useState('');
  const [message, setMessage] = useState('');
  const [showAddForm, setShowAddForm] = useState(false);
  const [newUser, setNewUser] = useState({
    firstName: '',
    lastName: '',
    username: '',
    email: '',
    password: '',
    role: 'user'
  });

  const navigate = useNavigate();

  useEffect(() => {
    fetchUsers();
  }, []);

  const fetchUsers = () => {
    fetch('http://localhost:5000/api/users')
      .then(res => res.json())
      .then(data => {
        const withOriginals = data.map(user => ({
          ...user,
          originalUsername: user.username
        }));
        setUsers(withOriginals);
      })
      .catch(() => setMessage('Failed to fetch users.'));
  };

  const handleInputChange = (index, field, value) => {
    const updated = [...users];
    updated[index][field] = value;
    setUsers(updated);
  };

  const handleUpdate = (user) => {
    fetch(`http://localhost:5000/api/user/update/${user.originalUsername}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(user)
    })
      .then(res => res.json())
      .then(data => {
        setMessage(data.message);
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
      .catch(() => setMessage('Update failed.'));
  };

  const handleDelete = (username) => {
    if (window.confirm(`Delete user '${username}'?`)) {
      fetch(`http://localhost:5000/api/user/delete/${username}`, {
        method: 'DELETE'
      })
        .then(res => res.json())
        .then(data => {
          setMessage(data.success ? 'User deleted.' : 'Delete failed.');
          fetchUsers();
        })
        .catch(() => setMessage('Error occurred.'));
    }
  };

  const handleAddUser = () => {
    const { firstName, lastName, username, email, password, role } = newUser;
    if (!firstName || !lastName || !username || !email || !password || !role) {
      alert('Please fill out all fields.');
      return;
    }
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(email)) {
      alert('Please enter a valid email address.');
      return;
    }
    if (password.length < 6) {
      alert('Password must be at least 6 characters long.');
      return;
    }

    fetch('http://localhost:5000/api/signup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(newUser)
    })
      .then(res => res.json())
      .then(data => {
        setMessage(data.message);
        if (data.success) {
          setNewUser({ firstName: '', lastName: '', username: '', email: '', password: '', role: 'user' });
          setShowAddForm(false);
          fetchUsers();
        } else {
          alert(data.message || 'User creation failed.');
        }
      })
      .catch(() => alert('Failed to create user. Please try again.'));
  };

  const filteredUsers = users.filter(u =>
    u.username.toLowerCase().includes(search.toLowerCase()) ||
    u.email.toLowerCase().includes(search.toLowerCase())
  );

  const tableInputStyle = {
    width: '100%',
    padding: '10px',
    backgroundColor: '#111',
    color: 'white',
    border: '1px solid #444',
    borderRadius: '4px'
  };

  return (
    <div className="admin-panel-wrapper">
      <div className="admin-sidebar">
        <h3>Admin Panel</h3>
        <ul>
          <li onClick={() => navigate('/admin-account-info')}>Account Info</li>
          <li onClick={() => navigate('/admin-security')}>Security</li>
          <li onClick={() => navigate('/admin-history')}>History</li>
          <li onClick={() => navigate('/admin-users')}>Manage Users</li>
        </ul>
      </div>

      <div className="admin-panel">
        <h2 className="section-title">Manage Users</h2>

        <input
          type="text"
          placeholder="Search by username or email..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ marginBottom: '20px', width: '100%', padding: '12px', backgroundColor: '#111', color: '#fff', border: '1px solid #333', borderRadius: '6px' }}
        />

        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', color: 'white' }}>
            <thead>
              <tr style={{ backgroundColor: '#222', borderBottom: '2px solid #444' }}>
                <th style={{ padding: '14px' }}>First Name</th>
                <th style={{ padding: '14px' }}>Last Name</th>
                <th style={{ padding: '14px' }}>Username</th>
                <th style={{ padding: '14px' }}>Email</th>
                <th style={{ padding: '14px' }}>Role</th>
                <th style={{ padding: '14px' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredUsers.map((user, index) => (
                <tr key={index} style={{ borderBottom: '1px solid #333', height: '65px' }}>
                  <td style={{ padding: '10px' }}><input style={tableInputStyle} value={user.firstName || ''} onChange={(e) => handleInputChange(index, 'firstName', e.target.value)} /></td>
                  <td style={{ padding: '10px' }}><input style={tableInputStyle} value={user.lastName || ''} onChange={(e) => handleInputChange(index, 'lastName', e.target.value)} /></td>
                  <td style={{ padding: '10px' }}><input style={tableInputStyle} value={user.username || ''} onChange={(e) => handleInputChange(index, 'username', e.target.value)} /></td>
                  <td style={{ padding: '10px' }}><input style={tableInputStyle} value={user.email || ''} onChange={(e) => handleInputChange(index, 'email', e.target.value)} /></td>
                  <td style={{ padding: '10px' }}>
                    <select style={tableInputStyle} value={user.role || ''} onChange={(e) => handleInputChange(index, 'role', e.target.value)}>
                      <option value="user">user</option>
                      <option value="admin">admin</option>
                    </select>
                  </td>
                  <td style={{ padding: '10px' }}>
                    <div style={{ display: 'flex', gap: '10px', justifyContent: 'center' }}>
                      <button className="update-btn" onClick={() => handleUpdate(user)} style={{ padding: '8px 14px', borderRadius: '6px', fontWeight: 'bold', border: 'none', cursor: 'pointer' }}>Update</button>
                      <button onClick={() => handleDelete(user.username)} style={{ backgroundColor: '#ff4d4d', padding: '8px 14px', borderRadius: '6px', color: 'white', fontWeight: 'bold', border: 'none', cursor: 'pointer' }}>Delete</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <hr style={{ margin: '40px 0', borderColor: '#333' }} />

        <button className="update-btn" style={{ marginBottom: '15px' }} onClick={() => setShowAddForm(!showAddForm)}>
          {showAddForm ? '➖ Cancel Add User' : '➕ Add New User'}
        </button>

        {showAddForm && (
          <div className="form-section" style={{ background: '#111', padding: '20px', borderRadius: '10px' }}>
            <h3 style={{ color: '#8B5DFF' }}>Add New User</h3>
            <input placeholder="First Name" value={newUser.firstName} onChange={(e) => setNewUser({ ...newUser, firstName: e.target.value })} />
            <input placeholder="Last Name" value={newUser.lastName} onChange={(e) => setNewUser({ ...newUser, lastName: e.target.value })} />
            <input placeholder="Username" value={newUser.username} onChange={(e) => setNewUser({ ...newUser, username: e.target.value })} />
            <input placeholder="Email" value={newUser.email} onChange={(e) => setNewUser({ ...newUser, email: e.target.value })} />
            <input placeholder="Password" type="password" value={newUser.password} onChange={(e) => setNewUser({ ...newUser, password: e.target.value })} />
            <select value={newUser.role} onChange={(e) => setNewUser({ ...newUser, role: e.target.value })}>
              <option value="user">user</option>
              <option value="admin">admin</option>
            </select>
            <button className="update-btn" onClick={handleAddUser} style={{ width: 'fit-content' }}>Create User</button>
          </div>
        )}

        {message && <p className="message">{message}</p>}
      </div>
    </div>
  );
};

export default AdminUserListPage;
