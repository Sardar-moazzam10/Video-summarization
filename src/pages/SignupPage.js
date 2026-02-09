import React, { useState } from 'react';
import './AuthPage.css';
import axios from 'axios';
import { useNavigate } from 'react-router-dom';

const SignupPage = () => {
  const [formData, setFormData] = useState({
    firstName: '',
    lastName: '',
    email: '',
    username: '',
    password: '',
    role: 'user'
  });
  const [message, setMessage] = useState('');
  const navigate = useNavigate();

  const handleChange = (e) => {
    setFormData((prev) => ({
      ...prev,
      [e.target.name]: e.target.value,
    }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setMessage('');

    try {
      const response = await axios.post('http://localhost:5000/api/signup', formData);

      if (response.data.success) {
        setMessage('Signup successful! Please log in.');
        setTimeout(() => navigate('/login'), 2000);
      } else {
        setMessage(response.data.message);
      }
    } catch (err) {
      setMessage('Signup failed. Please try again.');
    }
  };

  return (
    <div className="auth-container">
      <div className="auth-form-section">
        <h2 className="auth-title">Create Your Account</h2>
        <form className="auth-form" onSubmit={handleSubmit}>
          <div className="name-fields">
            <input
              type="text"
              placeholder="First Name"
              name="firstName"
              className="auth-input half-width"
              value={formData.firstName}
              onChange={handleChange}
              required
            />
            <input
              type="text"
              placeholder="Last Name"
              name="lastName"
              className="auth-input half-width"
              value={formData.lastName}
              onChange={handleChange}
              required
            />
          </div>
          <input
            type="email"
            placeholder="Email"
            name="email"
            className="auth-input"
            value={formData.email}
            onChange={handleChange}
            required
          />
          <input
            type="text"
            placeholder="Username"
            name="username"
            className="auth-input"
            value={formData.username}
            onChange={handleChange}
            required
          />
          <input
            type="password"
            placeholder="Password"
            name="password"
            className="auth-input"
            value={formData.password}
            onChange={handleChange}
            required
          />

          <div className="auth-extra">
            <label>
              <input type="checkbox" /> I agree to the Terms & Conditions
            </label>
          </div>

          <button type="submit" className="auth-button">Sign Up</button>

          {message && <p className="auth-message">{message}</p>}

          <p className="auth-footer">
            Already have an account? <a href="/login">Log in</a>
          </p>
        </form>
      </div>

      <div className="auth-image-section">
        <img src="/login-illustration.webp" alt="Illustration" />
      </div>
    </div>
  );
};

export default SignupPage;