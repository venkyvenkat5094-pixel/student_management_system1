def init_db():
    with app.app_context():
        db.create_all()

        if not Admin.query.filter_by(username="venkat").first():
            main_admin = Admin(
                admin_id="MAIN001",
                username="venkat",
                password="venky103project",
                role="superadmin"
            )
            db.session.add(main_admin)
            db.session.commit()


init_db()

if __name__ == "__main__":
    app.run(debug=True)
