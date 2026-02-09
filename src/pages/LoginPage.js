import React, { useState } from 'react';
import './AuthPage.css';
import axios from 'axios';
import { useNavigate } from 'react-router-dom';

const LoginPage = () => {
  const [login, setLogin] = useState('');
  const [password, setPassword] = useState('');
  const [message, setMessage] = useState('');
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setMessage('');

    try {
      const response = await axios.post('http://localhost:5000/api/login', {
        login,
        password,
      });

      if (response.data.success) {
        setMessage('Login successful!');
        localStorage.setItem(
          'user',
          JSON.stringify({
            role: response.data.role,
            username: response.data.username,
          })
        );

        if (response.data.role === 'admin') {
          navigate('/admin-account-info');
        } else {
          navigate('/');
        }
      } else {
        setMessage('Invalid credentials');
      }
    } catch (error) {
      setMessage('Login failed. Please try again.');
    }
  };

  return (
    <div className="auth-container">
      <div className="auth-form-section">
        <h2 className="auth-title">Welcome Back</h2>
        <form className="auth-form" onSubmit={handleSubmit}>
          <input
            type="text"
            placeholder="Email or Username"
            className="auth-input"
            value={login}
            onChange={(e) => setLogin(e.target.value)}
            required
          />
          <input
            type="password"
            placeholder="Password"
            className="auth-input"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          <div className="auth-extra">
           
            <a href="/forgot-password" className="auth-forgot">
              Forgot Password?
            </a>
          </div>
          <button type="submit" className="auth-button">
            Login
          </button>
          {message && <p className="auth-message">{message}</p>}
          <p className="auth-footer">
            Don't have an account? <a href="/signup">Sign Up</a>
          </p>
        </form>
      </div>
      <div className="auth-image-section">
        <img src="/login-illustration.webp" alt="Illustration" />
      </div>
    </div>
  );
};

export default LoginPage;
