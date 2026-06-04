import os
import datetime
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey, Date, Float
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from execution.config import DB_PATH

# Allow easy migration to Postgres later via ENV var
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_PATH}")

# SQLite specific argument checks
connect_args = {"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class GeneratedPin(Base):
    __tablename__ = "generated_pins"
    pin_id = Column(Integer, primary_key=True, autoincrement=True)
    idea_id = Column(Integer)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    seo_keywords = Column(Text)
    image_path = Column(String)
    destination_url = Column(String)
    status = Column(String, default='pending')
    rejection_reason = Column(Text)
    batch_date = Column(Date, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    blogs = relationship("Blog", back_populates="pin")
    schedules = relationship("PublishSchedule", back_populates="pin")

class Blog(Base):
    __tablename__ = "blogs"
    blog_id = Column(Integer, primary_key=True, autoincrement=True)
    pin_id = Column(Integer, ForeignKey("generated_pins.pin_id"))
    title = Column(String, nullable=False)
    html_content = Column(Text, nullable=False)
    category = Column(String)
    product_id = Column(Integer)
    wp_post_id = Column(Integer)
    wp_url = Column(String)
    wp_featured_image_id = Column(Integer)
    status = Column(String, default='generated')
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    published_at = Column(DateTime)

    pin = relationship("GeneratedPin", back_populates="blogs")

class PublishSchedule(Base):
    __tablename__ = "publish_schedule"
    schedule_id = Column(Integer, primary_key=True, autoincrement=True)
    pin_id = Column(Integer, ForeignKey("generated_pins.pin_id"))
    blog_id = Column(Integer)
    scheduled_time = Column(DateTime, nullable=False)
    status = Column(String, default='pending')
    error_message = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    completed_at = Column(DateTime)
    
    pin = relationship("GeneratedPin", back_populates="schedules")

class TrendyTopic(Base):
    __tablename__ = "trendy_topics"
    topic_id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String, nullable=False)
    details = Column(Text, nullable=False)
    source = Column(String, nullable=False)
    relevance_score = Column(Float, default=0.0)
    status = Column(String, default='pending')
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
