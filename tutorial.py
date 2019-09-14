def my_function():
    return range(0, 21)

def my_reverse(array):
    array.reverse()
    return array

def my_save(array):
    file = open("my_file.txt", "w")
    for item in array:
        file.write(str(item) + "\n")
    file.close()

def my_load(filename):
    file = open(filename, "r")

    sum = 0

    for line in file:
        sum += int(line)
    
    return sum

def main():
    my_save(my_reverse(my_function()))
    print(my_load("my_file.txt"))

main()