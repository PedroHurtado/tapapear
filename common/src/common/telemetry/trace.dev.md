📝 HTTP Request: POST /api/users/create
├── 🔐 middleware.AuthMiddleware (12ms)
│   └── ✅ user: john.doe@company.com | role: admin
├── 🚦 middleware.RateLimitMiddleware (3ms)
│   └── ✅ limit: 100/min | remaining: 87
├── 🎯 controller.UserController.create_user (187ms)
│   └── 📋 request: CreateUserRequest | correlation_id: corr-abc123
├── 📡 mediator.send (165ms)
│   ├── 📝 pipeline.LoggerPipeline (2ms)
│   ├── 🔄 pipeline.TransactionPipeline (138ms)
│   │   ├── 🎪 command_handler.CreateUserCommandHandler (125ms)
│   │   │   ├── 🔄 request_to_domain_command (3ms)
│   │   │   │   └── CreateUserRequest → CreateUserDomainCommand
│   │   │   ├── 👤 entity.User.create (45ms)
│   │   │   │   ├── ✅ business_rule: EmailUniqueness
│   │   │   │   ├── ✅ business_rule: PasswordComplexity  
│   │   │   │   └── 🎉 event_generated: UserCreatedEvent
│   │   │   └── 💾 repository.UserRepository.save (67ms)
│   │   │       ├── 🗄️ db.insert: users table (23ms)
│   │   │       └── 📤 events_dispatched: 1 event
│   │   └── ✅ transaction.commit (10ms)
│   └── 📝 pipeline.AuditPipeline (5ms)
└── 📢 mediator.notify (45ms)
   └── 🔔 notification_handler.SendWelcomeEmailHandler (42ms)
       ├── 🌐 http.client.notification-service (38ms)
       │   └── POST /api/emails/send → 200 OK
       └── ✅ email_sent: john.doe@company.com

📊 TRACE SUMMARY
├─ Total Duration: 245ms
├─ Spans: 15 (15 OK, 0 ERROR)  
├─ External Calls: 1
├─ Database Operations: 1
├─ Domain Events Generated: 1
├─ Pipelines Executed: 3
└─ Slowest Operation: pipeline.TransactionPipeline (138ms)

🎯 User: john.doe@company.com | 🆔 trace_id: 7a8b9c2d | 📧 user_id: usr_456789