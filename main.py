# Импортирование необходимых библиотек
import asyncio
import logging
import sqlite3
import random
from aiogram import Bot, Dispatcher, types
from aiogram.filters.command import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from config import BOT_TOKEN
from flask import Flask, request, jsonify, render_template, redirect, url_for
from tasks import tasks, add_task_sl


logging.basicConfig(level=logging.INFO)
app = Flask(__name__)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

#Веб-интерфейс для управления задачами
@app.route('/')
def index():
    # Функция для отображения списка задач на веб-странице
    tasks_with_indexes = {}
    for subject, task_list in tasks.items():
        tasks_with_indexes[subject] = []
        for i, task in enumerate(task_list):
            tasks_with_indexes[subject].append({"index": i, **task})  # Добавляем задачу с индексом в новый словарь
    return render_template('index.html', tasks=tasks_with_indexes)


@app.route('/add_task', methods=['POST'])  # Маршрут для добавления задачи
def handle_add_task():
    # Функция для обработки добавления новой задачи через веб-форму
    subject = request.form['subject']
    question = request.form['question']
    answer = request.form['answer']
    add_task_sl(subject, question, answer)
    return redirect(url_for('index'))


@app.route("/delete_task", methods=["POST"])  # Маршрут для удаления задачи (метод POST)
# Функция для обработки удаления задачи через веб-форму
def delete_task():
    subject = request.form["subject"]
    task_index = int(request.form["task_index"])
    print(f"Subject: {subject}")
    print(f"Task index: {task_index}")
    if subject in tasks:  # Проверка
        if 0 <= task_index < len(tasks[subject]):
            print(f"Deleting task {task_index} from {subject}")
            del tasks[subject][task_index]
        else:
            print(f"Error: Task index {task_index} out of range for subject {subject}")
    else:
        print(f"Error: Subject {subject} not found")

    return redirect(url_for("index"))


# Класс для определения состояний в FSM
class TaskForm(StatesGroup):
    subject = State()
    answer = State()
DATABASE = "tasks.db"


# Функция для создания таблицы в базе данных (если она не существует)
def create_db():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS results")
    cursor.execute("""
        CREATE TABLE results (
            user_id INTEGER,
            subject TEXT,
            true_answ INTEGER DEFAULT 0,
            total_tasks INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, subject)
        )
    """)
    conn.commit()
    conn.close()
create_db()


# Функция для получения списка задач по предмету
def get_tasks(subject):
    return tasks.get(subject, [])


def get_user_results(user_id, subject):
    # Функция для получения результатов пользователя по предмету из базы данных
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT true_answ, total_tasks FROM results WHERE user_id = ? AND subject = ?", (user_id, subject))
    result = cursor.fetchone()
    conn.close()
    if result:
        return {"true_answ": result[0], "total_tasks": result[1]}
    else:
        return {"true_answ": 0, "total_tasks": 0}


# Функция для обновления результатов пользователя по предмету в базе данных
def update_user_results(user_id, subject, true_answ, total_tasks):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO results (user_id, subject, true_answ, total_tasks)
        VALUES (?, ?, ?, ?)
    """, (user_id, subject, true_answ, total_tasks))
    conn.commit()
    conn.close()

# Обработчик команды /start
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    # Сбрасываем состояние при каждой команде /start
    await state.clear()
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Математика"),KeyboardButton(text="Русский"),]],resize_keyboard=True,)
    await message.answer("Выберите предмет:", reply_markup=keyboard)
    await state.set_state(TaskForm.subject)

# Обработчик команды /help
@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    help_text = (
        'Этот бот поможет вам подготовиться к экзамену, '
        'контрольной, или просто закрепить пройденный материал путем отправки заданий по разным предметам, '
        'таких как русский и математика, если вы захотите подготовиться по какому либо другому предмету, нужно оплатить\n'
        '\n'
        "Доступные команды:\n"
        "/start - Начать тестирование\n"
        "/results - Посмотреть результаты по предмету\n"
        "/help - Показать это сообщение\n"
        "/stop - завершить тест заранее"
    )
    await message.answer(help_text)


# Обработчик состояния TaskForm.subject (выбор предмета)
@dp.message(TaskForm.subject)
# Функция для обработки выбора предмета пользователем
async def process_subject(message: types.Message, state: FSMContext):
    subject = message.text.lower()
    if subject not in tasks:
        await message.answer("Предмет не найден. Пожалуйста, выберите из предложенных.")
        return
    await state.update_data(subject=subject, task_index=0, true_answ=0)
    await send_task(message, state)

# Функция для завершения теста
async def finish_test(message: types.Message, state: FSMContext):
    data = await state.get_data()
    subject = data.get("subject")
    true_answ = data.get("true_answ", 0)
    task_list = data.get("task_list", [])
    total_tasks = len(task_list)
    user_id = message.from_user.id
    if subject:
        update_user_results(user_id, subject, true_answ, total_tasks)

        await message.answer(
            f"Тест по предмету '{subject}' завершен!\n"
            f"Правильных ответов: {true_answ} из {total_tasks}.",
            reply_markup=ReplyKeyboardRemove(),
        )
    else:
        await message.answer("Тест завершен.", reply_markup=ReplyKeyboardRemove()) # Просто завершаем тест без результатов, если не выбран предмет
    await state.clear()


# Обработчик команды /stop
@dp.message(Command("stop"))
async def stop_test_handler(message: types.Message, state: FSMContext):
    await finish_test(message, state)


# Функция для отправки задачи пользователю
async def send_task(message: types.Message, state: FSMContext):
    data = await state.get_data()
    subject = data["subject"]
    task_index = data["task_index"]
    task_list = get_tasks(subject)  # Получаем обновленный список заданий
    if task_index == 0:
        random.shuffle(task_list)  # Перемешиваем список задач
        await state.update_data(task_list=task_list)
    task_list = (await state.get_data())["task_list"]
    task = task_list[task_index]
    await message.answer("Если Вы хотите завершить тест заранее - введите /stop")
    await message.answer(task["question"], reply_markup=ReplyKeyboardRemove())
    await state.set_state(TaskForm.answer)

# Добавить проверку task_index в process_answer
@dp.message(TaskForm.answer)
# Функция для обработки ответа пользователя
async def process_answer(message: types.Message, state: FSMContext):
    data = await state.get_data()
    subject = data["subject"]
    task_index = data["task_index"]
    task_list = data["task_list"]
    true_answ = data["true_answ"]
    task = task_list[task_index]
    user_answ = message.text.lower()
    if user_answ == task["answer"].lower():
        await message.answer("Правильно!")
        true_answ += 1
    else:
        await message.answer(f"Неправильно. Правильный ответ: {task['answer']}")
    task_index += 1
    if task_index >= len(task_list):
        await finish_test(message, state)
    else:
        await state.update_data(task_index=task_index, true_answ=true_answ)
        await send_task(message, state)


@dp.message(Command("results"))  # Обработчик команды /results
async def results(message: types.Message):
    # Выводим результаты если они есть
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Математика"),KeyboardButton(text="Русский"),]],resize_keyboard=True,)
    await message.answer("Выберите предмет, чтобы увидеть результаты:", reply_markup=keyboard)  # Отправляем сообщение с клавиатурой

@dp.message()  # Обработчик всех текстовых сообщений (без команды)
async def show_results(message: types.Message):
    # Функция для отображения результатов пользователя по предмету
    subject = message.text.lower()
    if subject not in tasks:
        await message.answer("Предмет не найден. Пожалуйста, выберите из предложенных.")
        return
    user_id = message.from_user.id
    results = get_user_results(user_id, subject)
    await message.answer(
        f"Ваши результаты по предмету '{subject}':\n"
        f"Правильных ответов: {results['true_answ']} из {results['total_tasks']}.",
    )


async def main():
    # Основная функция для запуска бота
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    async def start_all():
        # Функция для запуска Flask и aiogram одновременно
        from threading import Thread
        Thread(target=app.run, kwargs={'host': '0.0.0.0', 'port': 5000, 'debug': True, 'use_reloader': False}).start()
        # Запускаем Telegram-бота
        await main()
    asyncio.run(start_all())